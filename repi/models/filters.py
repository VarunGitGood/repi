from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass
class RetrievalFilters:
    source_service: str | None = None
    source_env: str | None = None
    log_level: str | list[str] | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    # Scopes retrieval to one project (UX P1). None = no project filter.
    project_id: UUID | None = None
