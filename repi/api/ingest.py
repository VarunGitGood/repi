import logging
from fastapi import APIRouter, UploadFile, File, Form, Depends
from pydantic import BaseModel
from repi.core.container import get_container

logger = logging.getLogger("repi.api.ingest")

router = APIRouter()

class IngestResponse(BaseModel):
    service: str
    chunk_count: int
    lines_total: int
    lines_with_timestamp: int
    level_counts: dict[str, int]
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
        stats = await ingestor.ingest(content_str, service)

    # Refresh the in-memory service list so a brand-new service is visible to
    # the intent resolver immediately, not only after a restart or GET /services.
    await container.init_known_services()

    message = f"Successfully ingested {stats.chunk_count} chunks for {service}"
    if stats.lines_total and stats.lines_with_timestamp == 0:
        message += (
            " (warning: no timestamps could be parsed from these logs — "
            "time-based filters will not match them)"
        )

    return IngestResponse(
        service=service,
        chunk_count=stats.chunk_count,
        lines_total=stats.lines_total,
        lines_with_timestamp=stats.lines_with_timestamp,
        level_counts=stats.level_counts,
        message=message,
    )
