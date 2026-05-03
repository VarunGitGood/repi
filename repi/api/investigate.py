import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from uuid import UUID

from repi.core.container import get_container
from repi.investigation.react_loop import InvestigationResult

logger = logging.getLogger("repi.api.investigate")

router = APIRouter()

class InvestigateRequest(BaseModel):
    query: str
    resume: bool = True

class InvestigationStepModel(BaseModel):
    step_number: int
    thought: str
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    observation_preview: Optional[str] = None

class InvestigationResponse(BaseModel):
    id: str
    query: str
    answer: str
    confidence: str
    duration_seconds: float
    steps: List[InvestigationStepModel]

@router.post("/investigate", response_model=InvestigationResponse)
async def investigate(request: InvestigateRequest):
    """
    Run an autonomous log investigation.
    """
    container = get_container()
    services = container.known_services
    
    async with container.get_session() as session:
        loop = container.get_investigation_loop(session)
        
        result: InvestigationResult = await loop.investigate(
            request.query,
            known_services=services,
            resume=request.resume
        )
    
    steps = []
    for s in result.steps:
        obs_str = str(s.observation.tool_result.result or s.observation.tool_result.error) if s.observation else None
        steps.append(InvestigationStepModel(
            step_number=s.step_number,
            thought=s.thought.content,
            tool_name=s.action.tool_call.name if s.action else None,
            tool_args=s.action.tool_call.args if s.action else None,
            observation_preview=obs_str[:200] + "..." if obs_str and len(obs_str) > 200 else obs_str
        ))
        
    return InvestigationResponse(
        id=result.id,
        query=result.query,
        answer=result.answer,
        confidence=result.confidence,
        duration_seconds=result.duration_seconds,
        steps=steps
    )

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
        loop = container.get_investigation_loop(session)
        store = loop.store
        if not store:
            raise HTTPException(status_code=500, detail="Store not configured")
        
        investigation = await store.get_by_id(uuid_obj)
        if not investigation:
            raise HTTPException(status_code=404, detail="Investigation not found")
        
        steps_data = await store.get_steps(uuid_obj)
        
    steps = []
    for s in steps_data:
        obs_str = str(s.observation.get("result") or s.observation.get("error")) if s.observation else None
        steps.append(InvestigationStepModel(
            step_number=s.step_number,
            thought=s.thought,
            tool_name=s.action.get("name") or s.action.get("tool") if s.action else None,
            tool_args=s.action.get("args") if s.action else None,
            observation_preview=obs_str[:200] + "..." if obs_str and len(obs_str) > 200 else obs_str
        ))
        
    return InvestigationResponse(
        id=str(investigation.id),
        query=investigation.query,
        answer=investigation.answer or "",
        confidence="unknown",
        duration_seconds=0.0,
        steps=steps
    )
