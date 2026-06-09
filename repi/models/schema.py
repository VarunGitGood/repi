from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, JSON
from pgvector.sqlalchemy import Vector
from sqlalchemy import TEXT, ARRAY, Index, String, Column, Computed, DateTime
from pydantic import field_validator
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

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
    # DB column is TIMESTAMPTZ (see db/schema.sql). Declaring the SQLAlchemy
    # column with timezone=True keeps the ORM in sync with the schema — without
    # this, SQLAlchemy binds the parameter as TIMESTAMP WITHOUT TIME ZONE and
    # rejects tz-aware Python datetimes from the asyncpg boundary.
    timestamp_start: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), index=True),
    )
    timestamp_end: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    text: str = Field(sa_column=Column(TEXT, nullable=False))
    id_values: Optional[List[str]] = Field(default=None, sa_column=Column(ARRAY(String)))
    embedding: Optional[List[float]] = Field(default=None, sa_column=Column(Vector(384)))
    log_metadata: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))
    # Read-only mirror of the DB's STORED generated column (see db/schema.sql).
    # `Computed(..., persisted=True)` is what tells SQLAlchemy "this is a
    # GENERATED ALWAYS column" so INSERT/UPDATE statements skip it. DDL is
    # owned by schema.sql; the expression here is duplicated only for
    # SQLAlchemy's metadata — keep the two in sync.
    text_tsv: Optional[Any] = Field(
        default=None,
        sa_column=Column(
            TSVECTOR,
            Computed(
                "setweight(to_tsvector('english', coalesce(text, '')), 'A') || "
                "setweight(to_tsvector('english', coalesce(source_service, '')), 'B') || "
                "setweight(to_tsvector('english', coalesce(log_level, '')), 'C')",
                persisted=True,
            ),
            nullable=True,
        ),
    )

class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    title: Optional[str] = Field(default=None, sa_column=Column(TEXT))
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    conversation_id: UUID = Field(index=True)
    role: str = Field(sa_column=Column(TEXT, nullable=False))  # "user" | "assistant"
    content: str = Field(sa_column=Column(TEXT, nullable=False))
    chunk_ids: List[str] = Field(default_factory=list, sa_column=Column(ARRAY(String)))
    confidence: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


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
    # A1/A2: optional thread back to a chat conversation, so the UI can render
    # an interleaved transcript. Not read by the ReAct loop — Deep Research is
    # intentionally stateless w.r.t. prior chat turns.
    conversation_id: Optional[UUID] = Field(default=None, index=True)

class InvestigationStep(SQLModel, table=True):
    __tablename__ = "investigation_steps"

    id: Optional[int] = Field(default=None, primary_key=True)
    investigation_id: UUID = Field(index=True)
    step_number: int
    thought: str = Field(sa_column=Column(TEXT))
    action: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    observation: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    kind: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class InvestigationChunk(SQLModel, table=True):
    __tablename__ = "investigation_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    investigation_id: UUID = Field(index=True)
    chunk_id: str = Field(index=True)
    service: Optional[str] = None
    timestamp: Optional[datetime] = None
    message: Optional[str] = Field(default=None, sa_column=Column(TEXT))


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
