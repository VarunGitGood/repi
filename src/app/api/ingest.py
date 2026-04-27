from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from src.app.api.dependencies import get_ingestor
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class IngestRequest(BaseModel):
    source_service: str
    source_env: str = "production"
    logs: str # Raw log text or JSONL string

@router.post("/api/v1/ingest")
async def ingest_logs(request: IngestRequest, ingestor: LogIngestor = Depends(get_ingestor)):
    if not request.source_service.strip():
        raise HTTPException(status_code=422, detail="source_service is missing or empty")
    
    chunks_ingested = await ingestor.ingest(
        logs=request.logs,
        source_service=request.source_service,
        source_env=request.source_env
    )
    
    return {
        "chunks_ingested": chunks_ingested,
        "source_service": request.source_service
    }
