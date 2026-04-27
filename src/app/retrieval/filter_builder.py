from __future__ import annotations
from typing import Any
from sqlalchemy import and_
from src.app.models.filters import RetrievalFilters
from src.app.models.schema import LogChunk

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
        exprs.append(LogChunk.timestamp_start >= filters.time_from)
        
    if filters.time_to:
        exprs.append(LogChunk.timestamp_end <= filters.time_to)
        
    return exprs
