"""Shared API request/response models.

Pydantic models for the HTTP surface, extracted out of the individual route
modules so they live in one tagged, importable place (mirrors the
``repi/models/`` convention for domain/db models). The route modules import
these back in; FastAPI behaviour, validation and the generated OpenAPI schema
are unchanged by the move.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Ingest ────────────────────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    service: str
    project: str
    chunk_count: int
    lines_total: int
    lines_with_timestamp: int
    level_counts: dict[str, int]
    message: str


# ── Watchers ──────────────────────────────────────────────────────────────────

class WatcherConfigCreate(BaseModel):
    service_name: str
    watch_path: str
    env: str = "production"
    enabled: bool = True
    project_id: UUID | None = None


class WatcherConfigRead(BaseModel):
    id: UUID
    service_name: str
    watch_path: str
    env: str
    enabled: bool
    project_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class WatcherConfigUpdate(BaseModel):
    service_name: str = None
    watch_path: str = None
    env: str = None
    enabled: bool = None
    project_id: UUID = None


class WatcherStatus(BaseModel):
    file_path: str
    offset: int
    last_seen_at: datetime
    updated_at: datetime


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    settings: dict[str, Any] = {}


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class ProjectRead(BaseModel):
    id: str
    name: str
    settings: dict[str, Any]
    service_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectService(BaseModel):
    name: str
    chunk_count: int
    last_seen: Optional[datetime] = None


# ── Conversations ─────────────────────────────────────────────────────────────

class ConversationSummary(BaseModel):
    id: str
    title: Optional[str]
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    created_at: str
    updated_at: str


class TranscriptTurn(BaseModel):
    mode: Literal["chat", "investigate"]
    id: str
    role: Optional[str] = None  # "user" | "assistant" for chat turns
    content: str
    chunk_ids: List[str] = []
    confidence: Optional[str] = None
    status: Optional[str] = None  # investigation status (chat turns leave this null)
    created_at: str


class ConversationDetail(BaseModel):
    id: str
    title: Optional[str]
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    created_at: str
    updated_at: str
    turns: List[TranscriptTurn]


# ── Investigations ────────────────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    # Capped to bound embedding + LLM prompt cost per request (a huge query
    # inflates token spend even within the rate limit).
    query: str = Field(..., max_length=2000)
    resume: bool = True
    # Optional thread back to a chat conversation. If omitted, a new
    # conversation row is created and its id returned so the UI can attach
    # subsequent /chat turns to the same thread.
    conversation_id: Optional[UUID] = None
    # Scopes retrieval + every ReAct tool to one project. If omitted but the
    # conversation has a project, the conversation's project applies.
    project_id: Optional[UUID] = None


class InvestigationStepModel(BaseModel):
    step_number: int
    thought: str
    # Preview fields for backwards compatibility; the list endpoint leaves them empty.
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    observation_preview: Optional[str] = None
    # Rich step shape used by the UI to render identically to the SSE stream.
    action: Optional[dict] = None
    observation: Optional[dict] = None
    kind: Optional[str] = None


class InvestigationResponse(BaseModel):
    id: str
    query: str
    status: str
    answer: Optional[str] = None
    created_at: datetime
    steps: List[InvestigationStepModel]
    pending_question: Optional[str] = None
    stats: Optional[dict] = None


class SimpleInvestigationResponse(BaseModel):
    id: str
    status: str
    conversation_id: Optional[str] = None


class ClarifyRequest(BaseModel):
    reply: str = Field(..., max_length=2000)


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatFilters(BaseModel):
    service: Optional[str] = None
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None
    entity: Optional[str] = None


class ChatRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    history: List[ChatTurn] = Field(default_factory=list, max_length=50)
    filters: Optional[ChatFilters] = None
    conversation_id: Optional[UUID] = None
    # Follow-up bias hint: chunk_ids the previous assistant turn cited. Used
    # by the chat path to fill in a missing service or time window from the
    # previous turn's chunks. Never overrides an explicit filter; silently
    # ignored if the IDs no longer resolve. Capped at 50 to bound the
    # indexed-PK fetch.
    previous_chunk_ids: List[str] = Field(default_factory=list, max_length=50)
    # Scopes retrieval + known-services resolution to one project. If
    # omitted but the conversation has a project, that project applies.
    project_id: Optional[UUID] = None
