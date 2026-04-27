from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

@dataclass
class RetrievalFilters:
    source_service: str | None = None
    source_env: str | None = None
    log_level: str | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
