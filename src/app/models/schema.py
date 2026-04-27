from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, Column, JSON
from pgvector.sqlalchemy import Vector
from sqlalchemy import TEXT, ARRAY, Index, String, Column
from sqlalchemy.dialects.postgresql import JSONB

class LogChunk(SQLModel, table=True):
    __tablename__ = "log_chunks"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    chunk_id: str = Field(index=True, unique=True)
    source_service: str = Field(index=True)
    source_env: str = Field(default="production", index=True)
    log_level: Optional[str] = Field(default=None, index=True)
    component: Optional[str] = Field(default=None)
    request_id: Optional[str] = Field(default=None)
    timestamp_start: Optional[datetime] = Field(default=None, index=True)
    timestamp_end: Optional[datetime] = Field(default=None)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    text: str = Field(sa_column=Column(TEXT, nullable=False))
    id_values: Optional[List[str]] = Field(default=None, sa_column=Column(ARRAY(String)))
    embedding: Optional[List[float]] = Field(default=None, sa_column=Column(Vector(384)))
    log_metadata: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))

    # Add GIN index for FTS manually if needed, but SQLModel doesn't have an easy way for GIN tsvector
    # We will use the migration script for that.
