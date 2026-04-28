from __future__ import annotations
import logging
import asyncpg
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from src.app.models.filters import RetrievalFilters
from src.app.retrieval.rrf import RRFRetrievalService

logger = logging.getLogger(__name__)

def _parse_iso_timestamp(ts: str | None) -> datetime | None:
    """Helper to parse ISO8601 strings with 'Z' support."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        logger.warning(f"Failed to parse timestamp: {ts}")
        return None

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

import uuid

def _is_valid_uuid(s: str) -> bool:
    """Check if a string is a valid UUID (Bug 4)."""
    try:
        uuid.UUID(str(s))
        return True
    except (ValueError, TypeError, AttributeError):
        return False

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
    filters = RetrievalFilters(
        source_service=service,
        log_level=level,
        time_from=_parse_iso_timestamp(time_from),
        time_to=_parse_iso_timestamp(time_to)
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
            "timestamp_start": data.get("timestamp_start").isoformat() if hasattr(data.get("timestamp_start"), "isoformat") else data.get("timestamp_start"),
            "timestamp_end": data.get("timestamp_end").isoformat() if hasattr(data.get("timestamp_end"), "isoformat") else data.get("timestamp_end"),
            "text": data.get("text"),
            "score": float(score)
        })
    return output

async def get_timeline(
    pool: asyncpg.Pool,
    chunk_ids: list[str],
) -> list[dict]:
    """Sort chunks by timestamp to see the sequence of events."""
    if not chunk_ids:
        return []
        
    rows = await pool.fetch(
        "SELECT chunk_id, source_service, log_level, timestamp_start, text FROM log_chunks WHERE chunk_id = ANY($1) ORDER BY timestamp_start",
        chunk_ids
    )
    
    return [{
        "chunk_id": r["chunk_id"],
        "service": r["source_service"],
        "level": r["log_level"],
        "timestamp": r["timestamp_start"].isoformat() if r["timestamp_start"] else None,
        "text": r["text"]
    } for r in rows]

async def find_co_occurring(
    pool: asyncpg.Pool,
    chunk_ids: list[str],
    window_seconds: int = 300,
) -> dict:
    """Find pairs of chunks from different services that occurred near each other."""
    if not chunk_ids:
        return {"results": []}
        
    # Bug 4 Fix: UUID validation
    invalid = [cid for cid in chunk_ids if not _is_valid_uuid(cid)]
    if invalid:
        return {
            "warning": (
                f"chunk_ids must be UUID strings returned by search_logs or get_timeline. "
                f"Invalid values received: {invalid}. "
                f"Call search_logs first and use the 'chunk_id' field from those results."
            ),
            "results": []
        }

    sql = """
    SELECT a.chunk_id as chunk_a_id, b.chunk_id as chunk_b_id,
           a.source_service as service_a, b.source_service as service_b,
           a.timestamp_start as time_a, b.timestamp_start as time_b,
           ABS(EXTRACT(EPOCH FROM (a.timestamp_start - b.timestamp_start))) as time_delta_seconds
    FROM log_chunks a
    JOIN log_chunks b
      ON a.source_service != b.source_service
      AND ABS(EXTRACT(EPOCH FROM (a.timestamp_start - b.timestamp_start))) < $1
    WHERE a.chunk_id = ANY($2)
      AND b.chunk_id = ANY($2)
    """
    
    rows = await pool.fetch(sql, window_seconds, chunk_ids)
    return {"results": [dict(row) for row in rows]}

async def get_service_summary(
    pool: asyncpg.Pool,
    service: str,
    time_from: str | None = None,
    time_to: str | None = None,
) -> dict:
    """Get high-level statistics for a service using raw SQL (Bug 1 Fix)."""
    time_from_dt = _parse_iso_timestamp(time_from)
    time_to_dt = _parse_iso_timestamp(time_to)

    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                                        AS total_chunks,
            COUNT(DISTINCT request_id)                                      AS unique_requests,
            COUNT(*) FILTER (WHERE log_level = 'ERROR')                    AS error_count,
            COUNT(*) FILTER (WHERE log_level = 'WARNING')                  AS warning_count,
            COUNT(*) FILTER (WHERE log_level = 'INFO')                     AS info_count,
            MIN(timestamp_start)                                            AS earliest,
            MAX(timestamp_end)                                              AS latest
        FROM log_chunks
        WHERE source_service = $1
          AND ($2::timestamptz IS NULL OR timestamp_start >= $2)
          AND ($3::timestamptz IS NULL OR timestamp_end   <= $3)
        """,
        service, time_from_dt, time_to_dt,
    )

    return {
        "service": service,
        "total_chunks": row["total_chunks"],
        "unique_requests": row["unique_requests"],
        "error_count": row["error_count"],
        "warning_count": row["warning_count"],
        "info_count": row["info_count"],
        "earliest": row["earliest"].isoformat() if row["earliest"] else None,
        "latest": row["latest"].isoformat() if row["latest"] else None,
    }

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
