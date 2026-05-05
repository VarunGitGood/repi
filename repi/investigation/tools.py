from __future__ import annotations
import logging
import asyncpg
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from repi.core.dates import DateHandler
from repi.models.filters import RetrievalFilters
from repi.retrieval.rrf import RRFRetrievalService

logger = logging.getLogger(__name__)

_parse_iso_timestamp = DateHandler.parse_iso

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

    if query and query.strip():
        results = await rrf_service.search(query=query, top_k=top_k, filters=filters)
    else:
        # No semantic query — skip RRF and do a direct filter+recency sort
        results = await rrf_service.vector_store.filter_search(filters=filters, top_k=top_k)

    chunk_ids = [res[0] for res in results]
    chunks_data = await rrf_service.vector_store.get_chunks_by_ids(chunk_ids)

    output = []
    for chunk_id, score in results:
        data = chunks_data.get(chunk_id, {})
        ts_start = data.get("timestamp_start")
        ts_end = data.get("timestamp_end")
        output.append({
            "chunk_id": chunk_id,
            "service": data.get("source_service"),
            "level": data.get("log_level"),
            "timestamp_start": DateHandler.to_iso(ts_start) if hasattr(ts_start, "isoformat") else ts_start,
            "timestamp_end": DateHandler.to_iso(ts_end) if hasattr(ts_end, "isoformat") else ts_end,
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
        "timestamp": DateHandler.to_iso(r["timestamp_start"]),
        "text": r["text"]
    } for r in rows]

async def find_co_occurring(
    pool: asyncpg.Pool,
    time_from: str,
    time_to: str,
    services: list[str] | None = None,
    level: str | None = None,
    top_k: int = 50,
) -> dict:
    """
    Fetch all log chunks across services in a time window, ordered chronologically.
    Use this to see exactly what was happening across the system at a specific moment.
    Unlike sweep_window (which gives counts/first-errors only), this returns full log text.
    """
    time_from_dt = _parse_iso_timestamp(time_from)
    time_to_dt = _parse_iso_timestamp(time_to)

    if time_from_dt is None or time_to_dt is None:
        return {"error": "time_from and time_to are required ISO8601 strings", "results": []}

    conditions = ["timestamp_start BETWEEN $1 AND $2"]
    params: list = [time_from_dt, time_to_dt]

    if services:
        params.append(services)
        conditions.append(f"source_service = ANY(${len(params)})")

    if level:
        params.append(level)
        conditions.append(f"log_level = ${len(params)}")

    params.append(top_k)
    sql = f"""
        SELECT chunk_id, source_service, log_level, timestamp_start, text
        FROM log_chunks
        WHERE {" AND ".join(conditions)}
        ORDER BY timestamp_start
        LIMIT ${len(params)}
    """

    rows = await pool.fetch(sql, *params)
    return {
        "window": [time_from, time_to],
        "total": len(rows),
        "results": [{
            "chunk_id": str(r["chunk_id"]),
            "service": r["source_service"],
            "level": r["log_level"],
            "timestamp": DateHandler.to_iso(r["timestamp_start"]),
            "text": r["text"],
        } for r in rows]
    }

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
        "earliest": DateHandler.to_iso(row["earliest"]),
        "latest": DateHandler.to_iso(row["latest"]),
    }

async def get_all_services(pool: asyncpg.Pool) -> list[str]:
    """Dynamically fetch all unique services currently in the database."""
    rows = await pool.fetch("SELECT DISTINCT source_service FROM log_chunks")
    return [r["source_service"] for r in rows]

from repi.investigation.sweep import auto_sweep

async def sweep_window(
    pool: asyncpg.Pool,
    time_from: str,
    time_to: str,
    exclude_services: list[str] | None = None,
) -> dict:
    """Sweep a time window for errors and warnings."""
    return await auto_sweep(
        pool=pool,
        time_from=_parse_iso_timestamp(time_from),
        time_to=_parse_iso_timestamp(time_to),
        exclude_services=exclude_services
    )

TOOL_SCHEMAS = {
    "search_logs": {
        "description": (
            "Search log chunks by semantic query, service, time range, and level. "
            "Pass an empty query to filter by service/level/time only (skips semantic ranking, returns most recent first)."
        ),
        "args": {
            "query": "string (pass empty string to filter-only)",
            "service": "string | null",
            "time_from": "ISO8601 string | null",
            "time_to": "ISO8601 string | null",
            "level": "ERROR | WARNING | INFO | DEBUG | null",
            "top_k": "int (default 10)",
        }
    },
    "get_timeline": {
        "description": (
            "Re-sort a set of already-found chunk IDs into strict chronological order. "
            "Use after collecting chunks from search_logs or sweep_window to reconstruct the event sequence."
        ),
        "args": {
            "chunk_ids": "list[string] (required)"
        }
    },
    "find_co_occurring": {
        "description": (
            "Fetch all log chunks across services in a time window, ordered chronologically. "
            "Use this to see full log text for everything happening across the system at a specific moment. "
            "Unlike sweep_window (counts + first-errors only), this returns actual log content."
        ),
        "args": {
            "time_from": "ISO8601 string (required)",
            "time_to": "ISO8601 string (required)",
            "services": "list[string] | null — filter to specific services, or null for all",
            "level": "ERROR | WARNING | INFO | DEBUG | null",
            "top_k": "int (default 50)",
        }
    },
    "get_service_summary": {
        "description": "Get high-level stats (counts, levels, time range) for a service",
        "args": {
            "service": "string (required)",
            "time_from": "ISO8601 string | null",
            "time_to": "ISO8601 string | null"
        }
    },
    "sweep_window": {
        "description": "Sweep a time window across all services to find errors and warnings. Returns buckets by service and the chronological first errors.",
        "args": {
            "time_from": "ISO8601 string (required)",
            "time_to": "ISO8601 string (required)",
            "exclude_services": "list[string] | null"
        }
    },
    "submit_answer": {
        "description": "Submit the final investigation answer once the root cause is identified. MUST follow the structured schema.",
        "args": {
            "root_cause": "string (required)",
            "incident_window": {"start": "ISO8601", "end": "ISO8601"},
            "affected_services": "list[string]",
            "trigger_event": {"service": "string", "timestamp": "ISO8601", "log_line": "string", "chunk_id": "string"},
            "propagation_chain": "list[{'ts': 'ISO8601', 'service': 'string', 'what': 'string', 'chunk_id': 'string'}]",
            "ruled_out_hypotheses": "list[{'hypothesis': 'string', 'why_ruled_out': 'string'}]",
            "assumptions": "list[string]",
            "confidence": "low | medium | high",
            "gaps": "list[string]"
        }
    }
}
