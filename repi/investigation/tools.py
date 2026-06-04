from __future__ import annotations
import asyncio
import logging
import asyncpg
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from repi.core.dates import DateHandler
from repi.models.filters import RetrievalFilters
from repi.retrieval.rrf import RRFRetrievalService

logger = logging.getLogger(__name__)

def _parse_iso_timestamp(ts):
    """Parse an ISO timestamp into a tz-aware UTC datetime.

    asyncpg's `timestamptz` codec interprets *naive* Python datetimes via the
    process's local timezone — on a non-UTC host that silently shifts query
    windows. We attach UTC at the asyncpg boundary so internal "naive UTC"
    callers don't have to know about it.
    """
    return DateHandler.to_aware_utc(DateHandler.parse_iso(ts))

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

async def scan_window(
    pool: asyncpg.Pool,
    time_from: str,
    time_to: str,
    level: list[str] | None = None,
    services: list[str] | None = None,
    top_k: int = 50,
    pre_context_seconds: int = 60,
    pre_context_per_service_limit: int = 20,
) -> dict:
    """
    Two-phase scan: ERROR/WARNING symptoms + a level-agnostic walk-back that
    captures the cause (migration, deploy, key rotation, config reload, etc.)
    regardless of how it was logged.

    Phase 1 — symptoms. Returns per-service ERROR/WARNING counts (`summary`)
    and the matching log lines (`logs`) within [time_from, time_to].

    Phase 2 — pre-context. For each service that emitted an ERROR in the
    window, looks back `pre_context_seconds` seconds before that service's
    first ERROR and returns any non-ERROR, non-DEBUG lines (`pre_context_logs`).
    Levels are NOT filtered to INFO/WARNING — INFO, WARNING, NOTICE, CRITICAL,
    FATAL, and any custom level are all candidates, because trigger events
    don't follow a universal level convention. DEBUG is excluded as noise;
    ERROR is excluded because phase 1 already covers it. Within each service,
    only the `pre_context_per_service_limit` lines closest to the first ERROR
    are returned (the rest are older, less likely to be the trigger).

    Pass `pre_context_seconds=0` to disable the walk-back entirely. See
    docs/two-phase-scan.md for the design rationale.
    """
    time_from_dt = _parse_iso_timestamp(time_from)
    time_to_dt = _parse_iso_timestamp(time_to)

    if time_from_dt is None or time_to_dt is None:
        return {
            "error": "time_from and time_to are required ISO8601 strings",
            "summary": {},
            "logs": [],
            "pre_context_logs": [],
            "total": 0,
        }

    effective_level = level if level else ["ERROR", "WARNING"]

    summary_sql = """
        SELECT source_service,
               COUNT(*) FILTER (WHERE log_level = 'ERROR')                     AS errors,
               COUNT(*) FILTER (WHERE log_level = 'WARNING')                   AS warnings,
               MIN(timestamp_start) FILTER (WHERE log_level = 'ERROR')         AS first_error
        FROM log_chunks
        WHERE timestamp_start BETWEEN $1 AND $2
          AND log_level IN ('ERROR', 'WARNING')
          AND ($3::text[] IS NULL OR source_service = ANY($3))
        GROUP BY source_service
        ORDER BY first_error NULLS LAST
    """

    logs_sql = """
        SELECT chunk_id, source_service, log_level, timestamp_start, text
        FROM log_chunks
        WHERE timestamp_start BETWEEN $1 AND $2
          AND log_level = ANY($3)
          AND ($4::text[] IS NULL OR source_service = ANY($4))
        ORDER BY timestamp_start
        LIMIT $5
    """

    summary_rows, log_rows = await asyncio.gather(
        pool.fetch(summary_sql, time_from_dt, time_to_dt, services),
        pool.fetch(logs_sql, time_from_dt, time_to_dt, effective_level, services, top_k),
    )

    summary = {
        r["source_service"]: {
            "errors": r["errors"],
            "warnings": r["warnings"],
            "first_error": DateHandler.to_iso(r["first_error"]),
            "pre_context_count": 0,
        }
        for r in summary_rows
    }

    logs = [
        {
            "chunk_id": str(r["chunk_id"]),
            "service": r["source_service"],
            "level": r["log_level"],
            "timestamp": DateHandler.to_iso(r["timestamp_start"]),
            "text": r["text"],
        }
        for r in log_rows
    ]

    # Phase 2 — pre-context walk-back. One CTE fetches INFO/WARNING lines in
    # [first_error - pre_context_seconds, first_error) for every service that
    # produced an ERROR. Only services with a real first_error participate, so
    # services with only WARNINGs are excluded by design.
    pre_context_logs: list[dict] = []
    services_with_errors = [
        r["source_service"]
        for r in summary_rows
        if r["first_error"] is not None
    ]

    if pre_context_seconds > 0 and services_with_errors and pre_context_per_service_limit > 0:
        # Level-agnostic walk-back. Trigger events (migrations, key rotations,
        # deploys) don't follow a universal level convention — they show up as
        # INFO in some shops, NOTICE/CRITICAL/FATAL in others, sometimes with
        # no level at all. So we filter on *time proximity*, not level:
        #   - exclude ERROR (phase 1 already has those)
        #   - exclude DEBUG (too chatty to be useful here)
        #   - cap per-service to the N lines closest to the first error
        #     (DESC for the ROW_NUMBER ranking, then re-sort ASC for output)
        pre_context_sql = """
            WITH first_errors AS (
                SELECT source_service, MIN(timestamp_start) AS first_error
                FROM log_chunks
                WHERE timestamp_start BETWEEN $1 AND $2
                  AND log_level = 'ERROR'
                  AND source_service = ANY($3)
                GROUP BY source_service
            ),
            candidates AS (
                SELECT lc.chunk_id, lc.source_service, lc.log_level,
                       lc.timestamp_start, lc.text,
                       ROW_NUMBER() OVER (
                           PARTITION BY lc.source_service
                           ORDER BY lc.timestamp_start DESC
                       ) AS rn
                FROM log_chunks lc
                JOIN first_errors fe ON lc.source_service = fe.source_service
                WHERE lc.timestamp_start >= fe.first_error - ($4 || ' seconds')::interval
                  AND lc.timestamp_start <  fe.first_error
                  AND lc.log_level IS DISTINCT FROM 'ERROR'
                  AND lc.log_level IS DISTINCT FROM 'DEBUG'
            )
            SELECT chunk_id, source_service, log_level, timestamp_start, text
            FROM candidates
            WHERE rn <= $5
            ORDER BY source_service, timestamp_start
        """
        pre_rows = await pool.fetch(
            pre_context_sql,
            time_from_dt,
            time_to_dt,
            services_with_errors,
            str(pre_context_seconds),
            pre_context_per_service_limit,
        )
        pre_context_logs = [
            {
                "chunk_id": str(r["chunk_id"]),
                "service": r["source_service"],
                "level": r["log_level"],
                "timestamp": DateHandler.to_iso(r["timestamp_start"]),
                "text": r["text"],
            }
            for r in pre_rows
        ]
        for entry in pre_context_logs:
            svc = entry["service"]
            if svc in summary:
                summary[svc]["pre_context_count"] += 1

    return {
        "window": [time_from, time_to],
        "summary": summary,
        "logs": logs,
        "pre_context_logs": pre_context_logs,
        "total": len(logs),
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
            "level": "ERROR | WARNING | INFO | DEBUG | list of those | null",
            "top_k": "int (default 10)",
        }
    },
    "get_timeline": {
        "description": (
            "Re-sort a set of already-found chunk IDs into strict chronological order. "
            "Use after collecting chunks from search_logs or scan_window to reconstruct the event sequence."
        ),
        "args": {
            "chunk_ids": "list[string] (required)"
        }
    },
    "scan_window": {
        "description": (
            "Two-phase scan over a time window. Returns:\n"
            " - 'summary': per-service ERROR/WARNING counts and first_error timestamp.\n"
            " - 'logs': ERROR/WARNING log lines inside [time_from, time_to] (the SYMPTOMS).\n"
            " - 'pre_context_logs': any non-ERROR, non-DEBUG lines from\n"
            "   [first_error - pre_context_seconds, first_error) for each service that emitted\n"
            "   an ERROR. Level is NOT filtered to INFO/WARNING — INFO, WARNING, NOTICE,\n"
            "   CRITICAL, FATAL, and custom levels are all candidates, because trigger events\n"
            "   don't follow a universal level convention. ALWAYS inspect pre_context_logs\n"
            "   before naming a trigger_event; the first ERROR is rarely the cause.\n"
            "Use this as your first call whenever investigating a new time window."
        ),
        "args": {
            "time_from": "ISO8601 string (required)",
            "time_to": "ISO8601 string (required)",
            "level": "list[ERROR|WARNING|INFO|DEBUG] | null (default ['ERROR','WARNING']) — phase 1 symptom filter",
            "services": "list[string] | null — filter to specific services, or null for all",
            "top_k": "int (default 50) — phase 1 logs cap",
            "pre_context_seconds": "int (default 60) — look-back window before each service's first ERROR; pass 0 to disable",
            "pre_context_per_service_limit": "int (default 20) — keep at most N pre-context lines per service, ranked by proximity to the first ERROR",
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
