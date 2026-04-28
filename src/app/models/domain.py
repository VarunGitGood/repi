from __future__ import annotations
from pydantic import BaseModel, field_validator
from typing import Optional, List, Any

class SearchResult(BaseModel):
    chunk_id: str
    score: float
    text: str
    metadata: dict[str, Any]
    embedding: Optional[List[float]] = None

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
