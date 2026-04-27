from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from sqlalchemy import text
from sqlmodel import select, func, and_

from src.app.models.schema import LogChunk
from src.app.models.filters import RetrievalFilters
from src.app.retrieval.rrf import RRFRetrievalService
from src.app.retrieval.pgvector_store import PgVectorStore

logger = logging.getLogger(__name__)

@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]

@dataclass
class ToolResult:
    tool_name: str
    args: dict[str, Any]
    result: Any
    error: str | None = None

async def search_logs(
    rrf_service: RRFRetrievalService,
    query: str,
    service: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    level: str | None = None,
    top_k: int = 10,
) -> list[dict]:
    """Search log chunks by query, service, time range, and level."""
    parsed_from = datetime.fromisoformat(time_from.replace("Z", "+00:00")) if time_from else None
    parsed_to = datetime.fromisoformat(time_to.replace("Z", "+00:00")) if time_to else None
    
    filters = RetrievalFilters(
        source_service=service,
        log_level=level,
        time_from=parsed_from,
        time_to=parsed_to
    )
    
    results = await rrf_service.search(query=query, top_k=top_k, filters=filters)
    
    # Enrich with text and metadata
    chunk_ids = [res[0] for res in results]
    chunks_data = await rrf_service.vector_store.get_chunks_by_ids(chunk_ids)
    
    output = []
    for chunk_id, score in results:
        data = chunks_data.get(chunk_id, {})
        output.append({
            "chunk_id": chunk_id,
            "service": data.get("source_service"),
            "level": data.get("log_level"),
            "timestamp_start": data.get("timestamp_start"),
            "timestamp_end": data.get("timestamp_end"),
            "text": data.get("text"),
            "score": float(score)
        })
    return output

async def get_timeline(
    vector_store: PgVectorStore,
    chunk_ids: list[str],
) -> list[dict]:
    """Sort chunks by timestamp to see the sequence of events."""
    chunks_data = await vector_store.get_chunks_by_ids(chunk_ids)
    sorted_chunks = sorted(
        chunks_data.values(), 
        key=lambda x: x.get("timestamp_start") or datetime.min
    )
    
    return [{
        "chunk_id": c["chunk_id"],
        "service": c["source_service"],
        "level": c["log_level"],
        "timestamp": c["timestamp_start"],
        "text": c["text"]
    } for c in sorted_chunks]

async def find_co_occurring(
    vector_store: PgVectorStore,
    chunk_ids: list[str],
    window_seconds: int = 300,
) -> list[dict]:
    """Find pairs of chunks from different services that occurred near each other."""
    if not chunk_ids:
        return []
        
    sql = """
    SELECT a.chunk_id as chunk_a, b.chunk_id as chunk_b,
           a.source_service as service_a, b.source_service as service_b,
           a.timestamp_start as time_a, b.timestamp_start as time_b
    FROM log_chunks a
    JOIN log_chunks b
      ON a.source_service != b.source_service
      AND ABS(EXTRACT(EPOCH FROM (a.timestamp_start - b.timestamp_start))) < :window
    WHERE a.chunk_id = ANY(:ids)
      AND b.chunk_id = ANY(:ids)
    """
    
    async with vector_store.session.connection() as conn:
        result = await vector_store.session.execute(text(sql), {"window": window_seconds, "ids": chunk_ids})
        return [dict(row._mapping) for row in result.all()]

async def get_service_summary(
    vector_store: PgVectorStore,
    service: str,
    time_from: str | None = None,
    time_to: str | None = None,
) -> dict:
    """Get high-level statistics for a service."""
    from_dt = datetime.fromisoformat(time_from.replace("Z", "+00:00")) if time_from else None
    to_dt = datetime.fromisoformat(time_to.replace("Z", "+00:00")) if time_to else None
    
    statement = select(
        func.count(LogChunk.id).label("total_chunks"),
        func.count(LogChunk.log_level.filter(LogChunk.log_level == 'ERROR')).label("error_count"),
        func.count(LogChunk.log_level.filter(LogChunk.log_level == 'WARNING')).label("warning_count"),
        func.min(LogChunk.timestamp_start).label("earliest"),
        func.max(LogChunk.timestamp_end).label("latest")
    ).where(LogChunk.source_service == service)
    
    if from_dt:
        statement = statement.where(LogChunk.timestamp_start >= from_dt)
    if to_dt:
        statement = statement.where(LogChunk.timestamp_end <= to_dt)
        
    result = await vector_store.session.execute(statement)
    row = result.one()._asdict()
    
    # unique_requests (if metadata has request_id)
    # Since we don't have a rigid request_id column yet, we might check log_metadata
    # For now, let's just return what we have
    return row

TOOL_SCHEMAS = {
    "search_logs": {
        "description": "Search log chunks by query, service, time range, and level",
        "args": {
            "query": "string (required)",
            "service": "string | null",
            "time_from": "ISO8601 string | null",
            "time_to": "ISO8601 string | null",
            "level": "ERROR | WARNING | INFO | DEBUG | null",
            "top_k": "int (default 10)",
        }
    },
    "get_timeline": {
        "description": "Get a chronologically ordered list of events from specific chunk IDs",
        "args": {
            "chunk_ids": "list[string] (required)"
        }
    },
    "find_co_occurring": {
        "description": "Find chunks across different services that occurred within a time window of each other",
        "args": {
            "chunk_ids": "list[string] (required)",
            "window_seconds": "int (default 300)"
        }
    },
    "get_service_summary": {
        "description": "Get high-level stats (counts, levels, time range) for a service",
        "args": {
            "service": "string (required)",
            "time_from": "ISO8601 string | null",
            "time_to": "ISO8601 string | null"
        }
    }
}
