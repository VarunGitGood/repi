"""POST /chat — single-shot RAG over logs (A1).

Contract:
- Resolve intent (reuse `repi.intent.resolver`).
- If clarification needed → stream a `clarify` event and stop.
- RRF retrieve top-k. When entities are present (from resolver OR caller-supplied
  `filters.entity`), UNION (RRF top-k, find_logs_by_id top-k) and dedupe by
  chunk_id before sending to the LLM. This implements the A4 entity-bias spec.
- Build a focused system prompt ("answer from these log lines only, cite chunk_ids").
- Stream the answer as SSE: `delta` events for tokens / chunks, `done` event
  carrying citations + heuristic confidence + conversation_id.
- Persist both user and assistant turns to `chat_messages` keyed by
  `conversation_id` (creating the row if not supplied).

NOT in scope:
- ReAct loop / tools / multi-step (that's /investigate).
- Reading prior conversation history (deferred to #64 / A11). Phase 1 uses
  client-supplied `history` only, not a DB lookup.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sa_text

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
from repi.retrieval.cluster_view import cluster_chunks
from repi.retrieval.timeline_view import build_timeline

logger = logging.getLogger("repi.api.chat")

router = APIRouter()


# ── Request / response models ─────────────────────────────────────────────────


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatFilters(BaseModel):
    service: Optional[str] = None
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None
    entity: Optional[str] = None


class ChatRequest(BaseModel):
    query: str
    history: List[ChatTurn] = []
    filters: Optional[ChatFilters] = None
    conversation_id: Optional[UUID] = None
    # Followup-bias hint: chunk_ids the previous assistant turn cited. When
    # the current query is missing EITHER an explicit service or an explicit
    # time window, the chat path fills in just the missing dimension from
    # the previous turn's chunks — service via dominant-source check, time
    # via a `Settings.FOLLOWUP_BIAS_WINDOW_MINUTES` envelope around their
    # timestamps. Soft — never overrides an explicit filter, silently
    # ignored if the IDs no longer resolve.
    #
    # Capped at 50 to bound the indexed-PK fetch and reject malformed
    # payloads early. The legitimate caller only ever sends the last
    # assistant turn's citations (≤10 in practice).
    previous_chunk_ids: List[str] = Field(default_factory=list, max_length=50)
    # UX P1: scopes retrieval + known-services resolution to one project. If
    # omitted but the conversation has a project, that project applies.
    project_id: Optional[UUID] = None


# ── Module-level constants ────────────────────────────────────────────────────

# Caller-visible window on cited-chunk `text` in the SSE done payload. Locked
# to the same length the LLM prompt's evidence block uses so the UI never
# surfaces content the model didn't see.
CHUNK_TEXT_WINDOW = 600

# When the dominant service's count is at least this multiple of the
# runner-up's, treat it as "this is the conversation's service" and bias
# retrieval toward it. Below this ratio the previous turn straddled
# services (cross-service incident) — we let the resolver fan out instead.
SERVICE_DOMINANCE_RATIO = 2.0


# ── SSE envelope helpers ──────────────────────────────────────────────────────
# Matches `/investigations/{id}/stream` envelope: data: {json with `type`}\n\n.

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"


def _normalize_ts(value):
    """Canonicalise a `timestamp_start` field for the chat path's chunks list.

    The chunks the LLM, the cluster_view, and the timeline_view all read share
    one rule: `timestamp` is ISO 8601 string or None. Downstream comparisons
    (`<`, `>`, `sorted(...)`) rely on this — mixing `datetime` and `str` in
    one list would TypeError. Two source paths (RRF + entity-bias merge) feed
    this list; both run their `timestamp_start` through here so a future
    change to either source can't reintroduce mixed types.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return _dh.to_iso(value)
    return value  # already string-ish


# ── Confidence heuristic (chat path) ──────────────────────────────────────────
# Compiler floors don't apply — /chat has no compile step. Deterministic rules:
#   - 0 chunks gathered → low
#   - entities resolved but none literally present in any chunk → low
#   - < 3 chunks → medium
#   - else medium (we never claim 'high' from a single-shot RAG turn; the
#     ReAct loop earns 'high' via cross-service correlation)
def _chat_confidence(chunks: list[dict], entities: list[str]) -> str:
    if not chunks:
        return "low"
    if entities:
        joined = " ".join((c.get("text") or "") for c in chunks).lower()
        if not any(e.lower() in joined for e in entities):
            return "low"
    return "medium"


# ── System prompt ─────────────────────────────────────────────────────────────

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


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    container = get_container()
    container.require_llm()  # 409 up front if no API key is configured.

    async def event_generator():
        # Resolve or create the conversation row up front so every event the
        # client sees can carry the (eventual) conversation_id.
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
                # Validate it exists; if not, create one with this id so the
                # caller's pinned id keeps working (idempotent).
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

            # Persist the user turn immediately — the client gets a citation-free
            # echo if the LLM call errors out mid-stream.
            user_msg = ChatMessage(
                conversation_id=conversation_id,
                role="user",
                content=req.query,
            )
            session.add(user_msg)
            await session.commit()

        try:
            # ── Intent resolution ────────────────────────────────────────────
            now = _dh.now()
            known_services = await container.get_known_services(project_id) or []
            resolution = resolve_intent(req.query, known_services, now)

            if isinstance(resolution, ClarificationNeeded):
                # Lite contextual chat: a followup like "what services are
                # involved" has no id/service/time on its own, but the prior
                # turns in `history` already anchored the conversation. Don't
                # clarify in that case — proceed with an unbounded retrieval
                # and let the LLM use the history to answer.
                if req.history:
                    intent = ResolvedIntent(
                        time_from=None, time_to=None,
                        services=[], symptoms=[], entities=[],
                        assumed=["proceeding with prior conversation context"],
                    )
                else:
                    yield _sse("clarify", {
                        "question": resolution.question,
                        "missing_dims": resolution.missing_dims,
                        "conversation_id": str(conversation_id),
                    })
                    # Persist a clarification turn so the transcript view
                    # has something to render on reload, AND bump
                    # conversations.updated_at so the sidebar still floats
                    # this thread to the top (otherwise a clarify-only turn
                    # leaves the row stamped at user-message time only).
                    async with container.async_session_maker() as session:
                        session.add(ChatMessage(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=resolution.question,
                            chunk_ids=[],
                            confidence="low",
                        ))
                        await session.execute(
                            sa_text("UPDATE conversations SET updated_at = NOW() WHERE id = :cid"),
                            {"cid": conversation_id},
                        )
                        await session.commit()
                    yield _sse("done", {
                        "chunk_ids": [],
                        "confidence": "low",
                        "conversation_id": str(conversation_id),
                        "clarification": True,
                    })
                    return
            else:
                intent = resolution

            # ── Retrieval ────────────────────────────────────────────────────
            # Honour caller-supplied filters; fall back to resolver-derived.
            f = req.filters or ChatFilters()
            service = f.service or (intent.services[0] if intent.services else None)
            time_from = f.time_from or intent.time_from
            time_to = f.time_to or intent.time_to
            caller_entity = f.entity
            entities = list(intent.entities)
            if caller_entity and caller_entity not in entities:
                entities.append(caller_entity)

            # Followup bias: when the current query is missing EITHER an
            # explicit service or an explicit time window, fill in just the
            # missing dimension from the previous turn's cited chunks.
            # Indexed PK lookup, so cost is negligible vs the LLM call. Soft:
            # explicit filters always win.
            if req.previous_chunk_ids and (service is None or (time_from is None and time_to is None)):
                async with container.async_session_maker() as session:
                    prev_meta = await container.get_retrieval_service(session).vector_store.get_chunks_by_ids(
                        list(req.previous_chunk_ids)
                    )
                if prev_meta:
                    prev_services = [m.get("source_service") for m in prev_meta.values() if m.get("source_service")]
                    if service is None and prev_services:
                        # Narrow to the dominant service only if it's clearly
                        # dominant — top count >= SERVICE_DOMINANCE_RATIO ×
                        # runner-up. Otherwise the previous turn straddled
                        # services (a cross-service incident), and pinning
                        # one would hide the other half on the followup.
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
                # search_diverse over-fetches then service-stratifies the top-k
                # so a noisy single service can't crowd out the cross-service
                # signal a "why are payments failing" style query is really asking
                # about. See repi/retrieval/diversify.py for the rationale.
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
                            "score": 0.0,  # ILIKE has no score; use sentinel
                        })

            # ── LLM call ─────────────────────────────────────────────────────
            # No streaming on the provider interface yet — collect the full
            # answer, then emit it as one delta event followed by done. The SSE
            # envelope is unchanged; we can upgrade to token streaming later
            # without breaking the client.
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

            # Persist the assistant turn.
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

            # Event clusters across the retrieved top-K. Singletons are
            # dropped (they're already in the per-turn timeline); the panel
            # gives the user the "1842x JWT failures, 347x DB timeouts"
            # compression rather than a raw chunk list. Caveat the UI must
            # carry: this is *per-turn* over the retrieved chunks, not a
            # corpus-wide aggregate.
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

            # Incident timeline — chronologically ordered, run-collapsed view
            # of the same retrieved chunks. Reuses the in-memory list rather
            # than re-fetching via investigation.tools.get_timeline (one less
            # DB roundtrip per turn). Singletons stay so the user can see
            # the gap between events; runs collapse so 12 identical lines
            # become "x12 over 14:02–14:04".
            timeline = build_timeline(chunks)

            # Minimal projection of cited chunks for the UI's raw-evidence tab.
            # Saves a follow-up GET — the chat path already has the hydrated
            # list. Keep the text at the same 600-char window used in the LLM
            # prompt so the UI doesn't surface content the model didn't see.
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
            yield _sse("error", {"message": str(e), "conversation_id": str(conversation_id)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
