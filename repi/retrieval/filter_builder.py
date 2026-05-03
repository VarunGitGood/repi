from __future__ import annotations
from typing import Any
from datetime import datetime
from repi.models.filters import RetrievalFilters
from repi.models.schema import LogChunk

def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """Strip timezone info after converting to UTC. asyncpg requires naive datetimes for TIMESTAMP columns."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convert to UTC and then strip tzinfo
        dt_utc = dt.utcnow() # Wait, no, we should convert the given dt to UTC
        # Correct way to convert to UTC and strip:
        import datetime as dt_module
        dt_utc = dt.astimezone(dt_module.timezone.utc).replace(tzinfo=None)
        return dt_utc
    return dt

def build_filter_expressions(filters: RetrievalFilters) -> list[Any]:
    """Returns a list of SQLModel/SQLAlchemy filter expressions."""
    exprs = []
    
    if filters.source_service:
        exprs.append(LogChunk.source_service == filters.source_service)
    
    if filters.source_env:
        exprs.append(LogChunk.source_env == filters.source_env)
        
    if filters.log_level:
        exprs.append(LogChunk.log_level == filters.log_level)
        
    if filters.time_from:
        exprs.append(LogChunk.timestamp_start >= _to_naive_utc(filters.time_from))
        
    if filters.time_to:
        exprs.append(LogChunk.timestamp_end <= _to_naive_utc(filters.time_to))
        
    return exprs
