"""POST /chat — single-shot RAG over logs.

Contract:
- Resolve intent (reuse `repi.intent.resolver`).
- If clarification needed → proceed with unbounded retrieval anyway.
- RRF retrieve top-k. When entities are present, UNION
  (RRF top-k, find_logs_by_id top-k) and dedupe by chunk_id.
- Build a focused system prompt ("answer from these log lines only, cite chunk_ids").
- Stream the answer as SSE: `delta` events for tokens, `done` event
  carrying citations, heuristic confidence, and conversation_id.
- Persist both user and assistant turns to `chat_messages` keyed by
  `conversation_id` (creating the row if not supplied).
"""
# NOTE: deliberately NOT using `from __future__ import annotations`. FastAPI
# must see `req: ChatRequest` as the real Pydantic class to treat it as the
# request body; stringized annotations get demoted to a query param and the
# JSON body is never parsed (every /chat call then 422s). Python 3.11 evaluates
# `X | None` / `list[X]` at runtime natively, so no future import is needed.

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text as sa_text

from repi.api.limiter import limiter
from repi.core.container import get_container
from repi.core.config import get_settings
from repi.core.dates import default_date_handler as _dh
from repi.intent.resolver import (
    ClarificationNeeded,
    ResolvedIntent,
    resolve as resolve_intent,
)
from repi.investigation.tools import find_logs_by_id
from repi.llm.provider import Message
from repi.models.filters import RetrievalFilters
from repi.models.schema import ChatMessage, Conversation
from repi.api.schemas import ChatFilters, ChatRequest, ChatTurn
from repi.retrieval.cluster_view import cluster_chunks
from repi.retrieval.timeline_view import build_timeline

logger = logging.getLogger("repi.api.chat")

router = APIRouter()


# Caller-visible window on cited-chunk `text` in the SSE done payload. Locked
# to the same length the LLM prompt's evidence block uses so the UI never
# surfaces content the model didn't see.
CHUNK_TEXT_WINDOW = 600

# Minimum ratio of top-service count to runner-up count required to pin
# retrieval to one service on a follow-up turn. Below this, the previous
# turn straddled services and we let the resolver fan out.
SERVICE_DOMINANCE_RATIO = 2.0


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"


def _normalize_ts(value):
    """Canonicalise a `timestamp_start` field to ISO 8601 string or None.

    Downstream comparisons (`<`, `>`, `sorted(...)`) require a uniform type;
    mixing `datetime` and `str` in one list would TypeError.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return _dh.to_iso(value)
    return value


def _chat_confidence(chunks: list[dict], entities: list[str]) -> str:
    """Deterministic confidence rules for single-shot RAG:
      - 0 chunks → low
      - entities resolved but none literally present in any chunk → low
      - otherwise → medium (chat path never claims 'high').
    """
    if not chunks:
        return "low"
    if entities:
        joined = " ".join((c.get("text") or "") for c in chunks).lower()
        if not any(e.lower() in joined for e in entities):
            return "low"
    return "medium"


CHAT_SYSTEM_PROMPT = """\
You answer the user's question using ONLY the log lines provided below.
Be terse and human-readable: the user is debugging.

When you reference what happened, quote the relevant log line directly or
describe it (e.g. "auth-svc retried 4 times before degrading to manual
sync"). Do NOT include chunk_id values, hashes, or other internal
identifiers in your answer — they are noise to the user. Stick to service
names, timestamps, and the substance of the log lines.

Do NOT invent log content. If the provided lines do not answer the
question, say so plainly — "the logs provided don't show that" is a valid
answer.
"""


# No return-type annotation on purpose. With `from __future__ import annotations`
# a `-> StreamingResponse` hint becomes a stringized ForwardRef; FastAPI then
# tries to resolve it into a response model, fails, and silently demotes `req`
# to a query param — so the JSON body is never parsed and every /chat call 422s
# (and /openapi.json 500s). Dropping the hint is the reliable fix.
@router.post("/chat", response_model=None)
@limiter.limit("20/minute")
async def chat(request: Request, req: ChatRequest):
    container = get_container()
    container.require_llm()  # 409 if no API key is configured.

    async def event_generator():
        conversation_id = req.conversation_id
        project_id = req.project_id
        async with container.async_session_maker() as session:
            if conversation_id is None:
                conv = Conversation(title=req.query[:80], project_id=project_id)
                session.add(conv)
                await session.commit()
                await session.refresh(conv)
                conversation_id = conv.id
            else:
                # Idempotent: create the row with the caller's pinned id if missing.
                stmt = select(Conversation).where(Conversation.id == conversation_id)
                res = await session.exec(stmt)
                existing = res.first()
                if existing is None:
                    conv = Conversation(id=conversation_id, title=req.query[:80], project_id=project_id)
                    session.add(conv)
                    await session.commit()
                elif project_id is None:
                    # Inherit the conversation's project when not pinned.
                    project_id = existing.project_id

            # Persist the user turn before the LLM call so a mid-stream
            # error still leaves an echo in the transcript.
            user_msg = ChatMessage(
                conversation_id=conversation_id,
                role="user",
                content=req.query,
            )
            session.add(user_msg)
            await session.commit()

        try:
            now = _dh.now()
            known_services = await container.get_known_services(project_id) or []
            resolution = resolve_intent(req.query, known_services, now)

            if isinstance(resolution, ClarificationNeeded):
                # Chat path never blocks on missing dimensions; retrieve unfiltered.
                assumed = ["proceeding with prior conversation context"] if req.history else ["no specific filters — searching all logs"]
                intent = ResolvedIntent(
                    time_from=None, time_to=None,
                    services=[], symptoms=[], entities=[],
                    assumed=assumed,
                )
            else:
                intent = resolution

            # Caller-supplied filters override resolver-derived ones.
            f = req.filters or ChatFilters()
            service = f.service or (intent.services[0] if intent.services else None)
            time_from = f.time_from or intent.time_from
            time_to = f.time_to or intent.time_to
            caller_entity = f.entity
            entities = list(intent.entities)
            if caller_entity and caller_entity not in entities:
                entities.append(caller_entity)

            # Follow-up bias: fill in service or time window from the previous
            # turn's cited chunks when the current query left them implicit.
            if req.previous_chunk_ids and (service is None or (time_from is None and time_to is None)):
                async with container.async_session_maker() as session:
                    prev_meta = await container.get_retrieval_service(session).vector_store.get_chunks_by_ids(
                        list(req.previous_chunk_ids)
                    )
                if prev_meta:
                    prev_services = [m.get("source_service") for m in prev_meta.values() if m.get("source_service")]
                    if service is None and prev_services:
                        counts = Counter(prev_services).most_common()
                        top_svc, top_n = counts[0]
                        runner_up = counts[1][1] if len(counts) > 1 else 0
                        if runner_up == 0 or top_n >= SERVICE_DOMINANCE_RATIO * runner_up:
                            service = top_svc
                            logger.debug(
                                "chat followup-bias: pinned service=%s (top=%d, runner-up=%d)",
                                top_svc, top_n, runner_up,
                            )
                        else:
                            logger.debug(
                                "chat followup-bias: skipped service pin — "
                                "no dominant service (top=%d, runner-up=%d)",
                                top_n, runner_up,
                            )
                    if time_from is None and time_to is None:
                        prev_ts = [m.get("timestamp_start") for m in prev_meta.values() if m.get("timestamp_start")]
                        if prev_ts:
                            envelope = timedelta(minutes=get_settings().FOLLOWUP_BIAS_WINDOW_MINUTES)
                            anchor_min = min(prev_ts)
                            anchor_max = max(prev_ts)
                            time_from = anchor_min - envelope
                            time_to = anchor_max + envelope
                            logger.debug(
                                "chat followup-bias: time window %s → %s",
                                time_from, time_to,
                            )

            async with container.async_session_maker() as session:
                retrieval = container.get_retrieval_service(session)
                rrf_filters = RetrievalFilters(
                    source_service=service,
                    time_from=time_from,
                    time_to=time_to,
                    project_id=project_id,
                )
                # search_diverse stratifies the top-k across services so a
                # single noisy service can't crowd out cross-service signal.
                rrf_hits = await retrieval.search_diverse(query=req.query, top_k=10, filters=rrf_filters)
                rrf_chunk_ids = [cid for cid, _score in rrf_hits]
                chunks_by_id = await retrieval.vector_store.get_chunks_by_ids(rrf_chunk_ids)

            chunks: list[dict] = []
            seen: set[str] = set()
            for cid, score in rrf_hits:
                data = chunks_by_id.get(cid, {})
                if cid in seen:
                    continue
                seen.add(cid)
                chunks.append({
                    "chunk_id": cid,
                    "service": data.get("source_service"),
                    "level": data.get("log_level"),
                    "timestamp": _normalize_ts(data.get("timestamp_start")),
                    "text": data.get("text") or "",
                    "score": float(score),
                })

            # Entity-bias merge: UNION RRF + find_logs_by_id, deduped by chunk_id.
            if entities and container.pool is not None:
                for ent in entities:
                    extra = await find_logs_by_id(container.pool, entity=ent, top_k=20, project_id=project_id)
                    for c in extra:
                        if c["chunk_id"] in seen:
                            continue
                        seen.add(c["chunk_id"])
                        # Normalise key names to match the RRF shape above.
                        chunks.append({
                            "chunk_id": c["chunk_id"],
                            "service": c.get("service"),
                            "level": c.get("level"),
                            "timestamp": _normalize_ts(c.get("timestamp_start")),
                            "text": c.get("text") or "",
                            "score": 0.0,  # ILIKE has no score; sentinel value.
                        })

            evidence_block = json.dumps([
                {
                    "chunk_id": c["chunk_id"],
                    "service": c.get("service"),
                    "level": c.get("level"),
                    "timestamp": str(c.get("timestamp") or ""),
                    "text": (c.get("text") or "")[:CHUNK_TEXT_WINDOW],
                }
                for c in chunks
            ], indent=2, default=str)

            messages: list[Message] = [Message(role="system", content=CHAT_SYSTEM_PROMPT)]
            for turn in req.history:
                messages.append(Message(role=turn.role, content=turn.content))
            messages.append(Message(
                role="user",
                content=(
                    f"## Question\n{req.query}\n\n"
                    f"## Evidence (log chunks)\n```json\n{evidence_block}\n```\n\n"
                    "Answer the question from these chunks. Cite chunk_ids inline."
                ),
            ))

            answer = await container.llm_provider.complete(
                messages, max_tokens=1500, temperature=0.0
            )
            cited_ids = [c["chunk_id"] for c in chunks]
            confidence = _chat_confidence(chunks, entities)

            yield _sse("delta", {"text": answer})

            async with container.async_session_maker() as session:
                session.add(ChatMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    chunk_ids=cited_ids,
                    confidence=confidence,
                ))
                # Bump conversations.updated_at so the sidebar reorders.
                await session.execute(
                    sa_text("UPDATE conversations SET updated_at = NOW() WHERE id = :cid"),
                    {"cid": conversation_id},
                )
                await session.commit()

            # Per-turn event clusters across the retrieved top-K (not corpus-wide).
            clusters = [
                {
                    "signature": v.signature,
                    "count": v.count,
                    "services": v.services,
                    "first_ts": v.first_ts,
                    "last_ts": v.last_ts,
                }
                for v in cluster_chunks(chunks)
            ]

            # Chronological, run-collapsed timeline over the retrieved chunks.
            timeline = build_timeline(chunks)

            # Cited chunks projection for the UI's raw-evidence tab, capped at
            # the same window the LLM prompt used.
            cited_chunks = [
                {
                    "chunk_id": c["chunk_id"],
                    "service": c.get("service"),
                    "level": c.get("level"),
                    "timestamp": str(c.get("timestamp") or "") or None,
                    "text": (c.get("text") or "")[:CHUNK_TEXT_WINDOW],
                }
                for c in chunks
            ]

            yield _sse("done", {
                "chunk_ids": cited_ids,
                "confidence": confidence,
                "conversation_id": str(conversation_id),
                "entities": entities,
                "clusters": clusters,
                "timeline": timeline,
                "cited_chunks": cited_chunks,
            })

        except Exception as e:
            logger.exception("chat endpoint raised")
            yield _sse("error", {"message": "An internal error occurred", "conversation_id": str(conversation_id)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
