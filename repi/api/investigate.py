import json
import asyncio
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from repi.core.container import get_container
from repi.investigation.react_loop import InvestigationStep

logger = logging.getLogger("repi.api.investigate")

router = APIRouter()

class InvestigateRequest(BaseModel):
    query: str
    resume: bool = True

class InvestigationStepModel(BaseModel):
    step_number: int
    thought: str
    # Legacy preview fields — kept for back-compat with anything that may still
    # read them. The list endpoint returns empty steps anyway.
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    observation_preview: Optional[str] = None
    # Rich shape the UI uses to render a step identically to the SSE stream.
    action: Optional[dict] = None
    observation: Optional[dict] = None
    kind: Optional[str] = None

class InvestigationResponse(BaseModel):
    id: str
    query: str
    status: str
    answer: Optional[str] = None
    created_at: datetime
    steps: List[InvestigationStepModel]
    pending_question: Optional[str] = None
    stats: Optional[dict] = None

class SimpleInvestigationResponse(BaseModel):
    id: str
    status: str

class ClarifyRequest(BaseModel):
    reply: str

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

@router.post("/investigate", response_model=SimpleInvestigationResponse)
async def investigate(request: InvestigateRequest):
    """
    Start an autonomous log investigation (non-blocking).
    """
    container = get_container()
    container.require_llm()  # 409 up front if no API key has been configured yet.
    async with container.get_session() as session:
        store = container.get_investigation_store(session)
        investigation = await store.get_or_create(request.query)

    # /stream handles execution: replays from DB if done, runs the loop live if not.
    return SimpleInvestigationResponse(
        id=str(investigation.id),
        status=investigation.status
    )

@router.post("/investigations/{investigation_id}/clarify", response_model=SimpleInvestigationResponse)
async def clarify_investigation(investigation_id: str, request: ClarifyRequest):
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
        
        await store.resume_from_clarification(uuid_obj, request.reply)
        
    return SimpleInvestigationResponse(
        id=investigation_id,
        status="running"
    )

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

    async def event_generator():
        container = get_container()
        async with container.get_session() as session:
            loop = container.get_investigation_loop(session)
            store = loop.store
            investigation = await store.get_by_id(uuid_obj)
            
            if not investigation:
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Investigation not found'}})}\n\n"
                return

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
                yield f"data: {json.dumps({'type': 'step', 'data': step_data})}\n\n"

            if investigation.status in ("completed", "failed"):
                yield f"data: {json.dumps({'type': 'phase_change', 'data': {'phase': 'done'}})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'data': {'answer': investigation.answer}})}\n\n"
                return

            if investigation.status == "awaiting_clarification":
                question = investigation.pending_question or ""
                yield f"data: {json.dumps({'type': 'clarification_request', 'data': {'question': question, 'investigation_id': investigation_id}})}\n\n"
                return

            queue = asyncio.Queue()

            async def on_step(step: InvestigationStep):
                step_data = {
                    "step_number": step.step_number,
                    "thought": step.thought.content,
                    "action": {"tool": step.action.tool_call.name, "args": step.action.tool_call.args} if step.action else None,
                    "observation": step.observation.tool_result.result if step.observation else None,
                    "kind": step.kind,
                }
                await queue.put({"type": "step", "data": step_data})

            async def on_phase_change(phase: str):
                await queue.put({"type": "phase_change", "data": {"phase": phase}})

            task = asyncio.create_task(loop.investigate(
                investigation.query,
                investigation_id=uuid_obj,
                on_step=on_step,
                on_phase_change=on_phase_change,
                resume=True
            ))

            while True:
                if task.done() and queue.empty():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    continue

            try:
                result = await task
                done_payload = {"answer": result.answer, "stats": result.stats}
                yield f"data: {json.dumps({'type': 'done', 'data': done_payload})}\n\n"
            except Exception as e:
                logger.error(f"Investigation failed: {e}")
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"

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
