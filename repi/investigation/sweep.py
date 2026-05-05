from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

import asyncpg

from repi.core.dates import DateHandler

logger = logging.getLogger(__name__)


async def auto_sweep(
    pool: asyncpg.Pool,
    time_from: datetime,
    time_to: datetime,
    exclude_services: Optional[list[str]] = None,
) -> dict:
    exclude_services = exclude_services or []

    if exclude_services:
        rows = await pool.fetch(
            """
            SELECT chunk_id, source_service, log_level, timestamp_start
            FROM log_chunks
            WHERE timestamp_start BETWEEN $1 AND $2
              AND log_level IN ('ERROR', 'WARNING')
              AND source_service != ALL($3)
            ORDER BY timestamp_start
            LIMIT 50
            """,
            time_from, time_to, exclude_services,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT chunk_id, source_service, log_level, timestamp_start
            FROM log_chunks
            WHERE timestamp_start BETWEEN $1 AND $2
              AND log_level IN ('ERROR', 'WARNING')
            ORDER BY timestamp_start
            LIMIT 50
            """,
            time_from, time_to,
        )

    buckets: dict[str, dict] = {}
    for row in rows:
        svc = row["source_service"]
        if svc not in buckets:
            buckets[svc] = {"errors": 0, "warnings": 0, "first_error": None, "chunk_ids": []}
        b = buckets[svc]
        b["chunk_ids"].append(str(row["chunk_id"]))
        if row["log_level"] == "ERROR":
            b["errors"] += 1
            ts = row["timestamp_start"]
            if b["first_error"] is None or ts < b["first_error"]:
                b["first_error"] = ts
        else:
            b["warnings"] += 1

    services_with_errors = []
    for svc, b in buckets.items():
        first = b["first_error"]
        services_with_errors.append({
            "service": svc,
            "errors": b["errors"],
            "warnings": b["warnings"],
            "first_error": DateHandler.to_iso(first),
            "chunk_ids": b["chunk_ids"],
        })

    services_with_errors.sort(key=lambda x: x["first_error"] or "")

    ordered_first_errors = []
    for s in services_with_errors:
        if s["first_error"]:
            ordered_first_errors.append(f"{s['service']}@{s['first_error']}")

    return {
        "window": [DateHandler.to_iso(time_from), DateHandler.to_iso(time_to)],
        "services_with_errors": services_with_errors,
        "ordered_first_errors": ordered_first_errors,
        "total_chunks_found": len(rows),
    }
