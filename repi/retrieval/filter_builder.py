from __future__ import annotations
from typing import Any
from repi.core.dates import DateHandler
from repi.models.filters import RetrievalFilters
from repi.models.schema import LogChunk


def build_filter_expressions(filters: RetrievalFilters) -> list[Any]:
    """Returns a list of SQLModel/SQLAlchemy filter expressions."""
    exprs = []

    if filters.source_service:
        exprs.append(LogChunk.source_service == filters.source_service)

    if filters.source_env:
        exprs.append(LogChunk.source_env == filters.source_env)

    if filters.log_level:
        if isinstance(filters.log_level, (list, tuple, set)):
            levels = [str(lvl).upper() for lvl in filters.log_level if lvl]
            if len(levels) == 1:
                exprs.append(LogChunk.log_level == levels[0])
            elif len(levels) > 1:
                exprs.append(LogChunk.log_level.in_(levels))
        else:
            exprs.append(LogChunk.log_level == str(filters.log_level).upper())

    # asyncpg interprets naive datetimes via the process's local timezone when
    # binding to `timestamptz` columns. Attach UTC explicitly at the DB
    # boundary so a non-UTC host (e.g. IST/+05:30) doesn't silently shift the
    # query window.
    if filters.time_from:
        exprs.append(LogChunk.timestamp_start >= DateHandler.to_aware_utc(filters.time_from))

    if filters.time_to:
        exprs.append(LogChunk.timestamp_end <= DateHandler.to_aware_utc(filters.time_to))

    return exprs
