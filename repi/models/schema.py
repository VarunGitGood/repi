from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, Column, JSON
from pgvector.sqlalchemy import Vector
from sqlalchemy import TEXT, ARRAY, Index, String, Column
from pydantic import field_validator
from sqlalchemy.dialects.postgresql import JSONB

class LogChunk(SQLModel, table=True):
    __tablename__ = "log_chunks"

    @field_validator("embedding", mode="before")
    @classmethod
    def coerce_embedding(cls, v):
        if v is None:
            return None
        if hasattr(v, "tolist"):   # numpy ndarray
            return v.tolist()
        if isinstance(v, (list, tuple)):
            return list(v)
        return v

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

class Investigation(SQLModel, table=True):
    __tablename__ = "investigations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    query: str = Field(sa_column=Column(TEXT))
    status: str = Field(default="started", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    current_step: int = Field(default=1)
    time_windows_tried: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSONB))
    services_seen: Optional[list[str]] = Field(default_factory=list, sa_column=Column(JSONB))
    total_llm_calls: int = Field(default=0)
    answer: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    # Valid statuses: "started", "running", "completed", "failed", "awaiting_clarification"
    pending_question: Optional[str] = Field(default=None, nullable=True)

class InvestigationStep(SQLModel, table=True):
    __tablename__ = "investigation_steps"

    id: Optional[int] = Field(default=None, primary_key=True)
    investigation_id: UUID = Field(index=True)
    step_number: int
    thought: str = Field(sa_column=Column(TEXT))
    action: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    observation: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=datetime.utcnow)

class InvestigationChunk(SQLModel, table=True):
    __tablename__ = "investigation_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    investigation_id: UUID = Field(index=True)
    chunk_id: str = Field(index=True)
    service: Optional[str] = None
    timestamp: Optional[datetime] = None
    message: Optional[str] = Field(default=None, sa_column=Column(TEXT))

    # Add GIN index for FTS manually if needed, but SQLModel doesn't have an easy way for GIN tsvector
    # We will use the migration script for that.

class WatcherConfig(SQLModel, table=True):
    __tablename__ = "watcher_configs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    service_name: str = Field(index=True)
    watch_path: str = Field(index=True)
    env: str = Field(default="production")
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class WatcherOffset(SQLModel, table=True):
    __tablename__ = "watcher_offsets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    watcher_config_id: UUID = Field(index=True)
    file_path: str = Field(index=True)
    offset: int = Field(default=0)
    last_seen_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
