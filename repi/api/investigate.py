import json
import asyncio
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from uuid import UUID
from datetime import datetime

from fastapi import Request as StarletteRequest

from repi.core.container import get_container
from repi.api.guards import llm_daily_budget
from repi.investigation.react_loop import InvestigationStep
from repi.api.limiter import limiter
from repi.api.schemas import (
    ClarifyRequest,
    InvestigateRequest,
    InvestigationResponse,
    InvestigationStepModel,
    SimpleInvestigationResponse,
)

logger = logging.getLogger("repi.api.investigate")

router = APIRouter()

@router.get("/investigations", response_model=List[InvestigationResponse])
async def list_investigations(limit: int = 20):
    """List recent investigations."""
    container = get_container()
    async with container.get_session() as session:
        store = container.get_investigation_store(session)
        items = await store.list_all(limit=limit)
        
        results = []
        for inv in items:
            results.append(InvestigationResponse(
                id=str(inv.id),
                query=inv.query,
                status=inv.status,
                answer=inv.answer,
                created_at=inv.created_at,
                steps=[]
            ))
        return results

@router.post("/investigate", response_model=SimpleInvestigationResponse,
             dependencies=[Depends(llm_daily_budget)])
@limiter.limit("3/minute")
async def investigate(request: StarletteRequest, request_body: InvestigateRequest):
    """
    Start an autonomous log investigation (non-blocking).

    `conversation_id` threads this investigation back to a chat surface for the
    transcript view. If omitted, a new conversation is created and returned.
    /investigate itself is stateless w.r.t. prior chat turns (Deep Research
    model) — the link is purely for UI threading.
    """
    container = get_container()
    container.require_llm()  # 409 up front if no API key has been configured yet.
    async with container.get_session() as session:
        # Lazy import — chat/conversations live alongside this module.
        from repi.models.schema import Conversation
        from sqlmodel import select as sm_select
        from sqlalchemy import text as sa_text

        conversation_id = request_body.conversation_id
        project_id = request_body.project_id
        if conversation_id is None:
            conv = Conversation(title=request_body.query[:80], project_id=project_id)
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            conversation_id = conv.id
        else:
            # Validate it exists; if not, materialise with the caller's id.
            stmt = sm_select(Conversation).where(Conversation.id == conversation_id)
            res = await session.exec(stmt)
            existing = res.first()
            if existing is None:
                session.add(Conversation(id=conversation_id, title=request_body.query[:80], project_id=project_id))
                await session.commit()
            elif project_id is None:
                # Inherit the conversation's project when the caller didn't pin one.
                project_id = existing.project_id

        store = container.get_investigation_store(session)
        investigation = await store.get_or_create(
            request_body.query, conversation_id=conversation_id, project_id=project_id
        )

        # Bump the conversation's updated_at so the sidebar surfaces the
        # thread to the top even when activity is investigation-side rather
        # than chat-side. Without this, running /investigate in an existing
        # conversation doesn't refresh its position in the sidebar list.
        await session.execute(
            sa_text("UPDATE conversations SET updated_at = NOW() WHERE id = :cid"),
            {"cid": conversation_id},
        )
        await session.commit()

    # /stream handles execution: replays from DB if done, runs the loop live if not.
    return SimpleInvestigationResponse(
        id=str(investigation.id),
        status=investigation.status,
        conversation_id=str(conversation_id),
    )

@router.post("/investigations/{investigation_id}/clarify", response_model=SimpleInvestigationResponse,
             dependencies=[Depends(llm_daily_budget)])
@limiter.limit("3/minute")
async def clarify_investigation(request: StarletteRequest, investigation_id: str,
                                request_body: ClarifyRequest):
    """
    Provide clarification for a paused investigation.
    """
    try:
        uuid_obj = UUID(investigation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid investigation ID format")

    container = get_container()
    async with container.get_session() as session:
        store = container.get_investigation_store(session)
        investigation = await store.get_by_id(uuid_obj)
        
        if not investigation:
            raise HTTPException(status_code=404, detail="Investigation not found")
        
        if investigation.status != "awaiting_clarification":
            raise HTTPException(status_code=409, detail=f"Investigation is in status {investigation.status}, not awaiting_clarification")
        
        await store.resume_from_clarification(uuid_obj, request_body.reply)
        
    return SimpleInvestigationResponse(
        id=investigation_id,
        status="running"
    )

class InvestigationBroadcaster:
    def __init__(self):
        self.listeners: set[asyncio.Queue] = set()

    def broadcast(self, event: dict):
        for q in list(self.listeners):
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.listeners.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self.listeners.discard(q)

INVESTIGATION_BROADCASTERS: dict[UUID, InvestigationBroadcaster] = {}

@router.get("/investigations/{investigation_id}/stream")
async def stream_investigation(investigation_id: str):
    """
    SSE endpoint to stream investigation steps.
    """
    try:
        uuid_obj = UUID(investigation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid investigation ID format")

    # 409 here is cheaper than failing mid-stream — once we enter the SSE
    # generator the response status is already 200 and the client only learns
    # something went wrong through an error event.
    get_container().require_llm()

    # Claim execution before the SSE 200 so concurrent streams can't both run
    # the (expensive) ReAct loop on one budgeted request.
    async with get_container().get_session() as _session:
        _store = get_container().get_investigation_store(_session)
        _inv = await _store.get_by_id(uuid_obj)
        if not _inv:
            raise HTTPException(status_code=404, detail="Investigation not found")
        
        if _inv.status not in ("completed", "failed", "awaiting_clarification"):
            # Only claim if it is not already running or we don't have a broadcaster for it
            if uuid_obj not in INVESTIGATION_BROADCASTERS:
                if _inv.status == "running":
                    # Stale status from a previous server run or crash, reset it
                    _inv.status = "started"
                    await _store.session.commit()
                
                if not await _store.claim_for_execution(uuid_obj):
                    raise HTTPException(status_code=409, detail="Investigation is already being streamed")

    async def event_generator():
        container = get_container()
        async with container.get_session() as session:
            store = container.get_investigation_store(session)
            investigation = await store.get_by_id(uuid_obj)

            if not investigation:
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Investigation not found'}})}\n\n"
                return

            # Build the loop scoped to the investigation's project: every tool
            # call carries project_id and the resolver sees only that
            # project's services.
            scoped_services = await container.get_known_services(investigation.project_id)
            
            steps = await store.get_steps(uuid_obj)
            for s in steps:
                # Persisted shape is {name, args}; the UI consumes {tool, args}
                # from the live SSE path. Normalize so replayed and live steps
                # render through the same component path.
                action_obj = None
                if s.action:
                    tool_name = s.action.get("tool") or s.action.get("name")
                    if tool_name:
                        action_obj = {"tool": tool_name, "args": s.action.get("args")}
                step_data = {
                    "step_number": s.step_number,
                    "thought": s.thought,
                    "action": action_obj,
                    "observation": s.observation,
                    "kind": getattr(s, "kind", None),
                }
                yield f"data: {json.dumps({'type': 'step', 'data': step_data}, default=str)}\n\n"

            if investigation.status in ("completed", "failed"):
                yield f"data: {json.dumps({'type': 'phase_change', 'data': {'phase': 'done'}})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'data': {'answer': investigation.answer}})}\n\n"
                return

            if investigation.status == "awaiting_clarification":
                question = investigation.pending_question or ""
                yield f"data: {json.dumps({'type': 'clarification_request', 'data': {'question': question, 'investigation_id': investigation_id}})}\n\n"
                return

            # Check if we need to start or attach to the background task
            is_creator = False
            if uuid_obj not in INVESTIGATION_BROADCASTERS:
                INVESTIGATION_BROADCASTERS[uuid_obj] = InvestigationBroadcaster()
                is_creator = True

            broadcaster = INVESTIGATION_BROADCASTERS[uuid_obj]
            queue = broadcaster.subscribe()

            if is_creator:
                async def on_step(step: InvestigationStep):
                    step_data = {
                        "step_number": step.step_number,
                        "thought": step.thought.content,
                        "action": {"tool": step.action.tool_call.name, "args": step.action.tool_call.args} if step.action else None,
                        "observation": step.observation.tool_result.result if step.observation else None,
                        "kind": step.kind,
                    }
                    broadcaster.broadcast({"type": "step", "data": step_data})

                async def on_phase_change(phase: str):
                    broadcaster.broadcast({"type": "phase_change", "data": {"phase": phase}})

                async def run_investigation():
                    async with container.get_session() as bg_session:
                        bg_store = container.get_investigation_store(bg_session)
                        bg_loop = container.get_investigation_loop(
                            bg_session,
                            project_id=investigation.project_id,
                            known_services=scoped_services,
                        )
                        try:
                            result = await bg_loop.investigate(
                                investigation.query,
                                investigation_id=uuid_obj,
                                on_step=on_step,
                                on_phase_change=on_phase_change,
                                resume=True
                            )
                            refreshed = await bg_store.get_by_id(uuid_obj)
                            if refreshed and refreshed.status == "awaiting_clarification":
                                question = refreshed.pending_question or ""
                                broadcaster.broadcast({
                                    "type": "clarification_request",
                                    "data": {"question": question, "investigation_id": investigation_id}
                                })
                            else:
                                done_payload = {"answer": result.answer, "stats": result.stats}
                                broadcaster.broadcast({"type": "done", "data": done_payload})
                        except Exception as e:
                            logger.error("Investigation failed", exc_info=True)
                            broadcaster.broadcast({"type": "error", "data": {"message": "Investigation failed"}})
                        finally:
                            INVESTIGATION_BROADCASTERS.pop(uuid_obj, None)

                asyncio.create_task(run_investigation())

            try:
                while True:
                    event = await queue.get()
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                    if event["type"] in ("done", "error", "clarification_request"):
                        break
            finally:
                broadcaster.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/investigations/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(investigation_id: str):
    """
    Retrieve details of a past investigation.
    """
    try:
        uuid_obj = UUID(investigation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid investigation ID format")

    container = get_container()
    async with container.get_session() as session:
        # Read-only fetch — go through the store directly. Using
        # get_investigation_loop() here would call require_llm() and 409 when no
        # LLM key is configured, blocking access to completed investigations.
        store = container.get_investigation_store(session)

        investigation = await store.get_by_id(uuid_obj)
        if not investigation:
            raise HTTPException(status_code=404, detail="Investigation not found")

        steps_data = await store.get_steps(uuid_obj)
        
    steps = []
    tools_called: set[str] = set()
    iterations = 0
    reflections = 0
    for s in steps_data:
        obs_str = str(s.observation.get("result") or s.observation.get("error")) if s.observation else None
        tool_name = (s.action.get("name") or s.action.get("tool")) if s.action else None
        tool_args = s.action.get("args") if s.action else None
        # The SSE stream sends action as {tool, args}; mirror that so the UI can
        # render replayed steps with the same component path as live ones.
        action_obj = {"tool": tool_name, "args": tool_args} if tool_name else None
        steps.append(InvestigationStepModel(
            step_number=s.step_number,
            thought=s.thought,
            tool_name=tool_name,
            tool_args=tool_args,
            observation_preview=obs_str[:200] + "..." if obs_str and len(obs_str) > 200 else obs_str,
            action=action_obj,
            observation=s.observation,
            kind=getattr(s, "kind", None),
        ))
        if s.kind == "reflection":
            reflections += 1
        elif not s.kind:
            iterations += 1
        if tool_name:
            tools_called.add(tool_name)

    stats: Optional[dict] = None
    if investigation.status in ("completed", "failed"):
        stats = {
            "iterations_used": iterations,
            "reflections_used": reflections,
            "tools_called": sorted(tools_called),
        }

    return InvestigationResponse(
        id=str(investigation.id),
        query=investigation.query,
        status=investigation.status,
        answer=investigation.answer,
        created_at=investigation.created_at,
        steps=steps,
        pending_question=investigation.pending_question,
        stats=stats,
    )
