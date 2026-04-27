from __future__ import annotations
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dataclasses import asdict

from src.app.api.dependencies import get_investigation_loop
from src.app.investigation.react_loop import InvestigationStep, ReactInvestigationLoop

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/investigate", tags=["investigation"])

class InvestigateRequest(BaseModel):
    query: str
    max_iterations: int = 8

@router.post("")
async def investigate_stream(
    request: InvestigateRequest,
    loop: ReactInvestigationLoop = Depends(get_investigation_loop)
):
    """
    Stream investigation steps (Chain of Thought) via SSE.
    """
    async def event_stream():
        try:
            async def on_step(step: InvestigationStep):
                event_data = {
                    "type": "step",
                    "step": step.step_number,
                    "thought": step.thought.content,
                    "action": {
                        "tool": step.action.tool_call.name,
                        "args": step.action.tool_call.args,
                    } if step.action else None,
                    "observation": step.observation.tool_result.result 
                                   if step.observation else (step.observation.tool_result.error if step.observation else None),
                }
                yield f"data: {json.dumps(event_data, default=str)}\n\n"

            # loop = container.get_investigation_loop()  <-- Old way
            result = await loop.investigate(request.query, on_step=on_step)

            # Final result event
            yield f"data: {json.dumps({'type': 'result', 'answer': result.answer, 'confidence': result.confidence, 'duration': result.duration_seconds})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Investigation stream failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/sync")
async def investigate_sync(
    request: InvestigateRequest,
    loop: ReactInvestigationLoop = Depends(get_investigation_loop)
):
    """
    Perform deep investigation and return final result synchronously.
    """
    try:
        # loop = container.get_investigation_loop()
        result = await loop.investigate(request.query)
        result = await loop.investigate(request.query)
        return asdict(result)
    except Exception as e:
        logger.error(f"Investigation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
