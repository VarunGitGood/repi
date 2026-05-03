import logging
from fastapi import APIRouter, UploadFile, File, Form, Depends
from pydantic import BaseModel
from repi.core.container import get_container

logger = logging.getLogger("repi.api.ingest")

router = APIRouter()

class IngestResponse(BaseModel):
    service: str
    chunk_count: int
    message: str

@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    service: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Ingest logs from a file for a specific service.
    """
    content = await file.read()
    content_str = content.decode("utf-8")
    
    container = get_container()
    async with container.get_session() as session:
        ingestor = container.get_ingestor(session)
        count = await ingestor.ingest(content_str, service)
    
    return IngestResponse(
        service=service,
        chunk_count=count,
        message=f"Successfully ingested {count} chunks for {service}"
    )
