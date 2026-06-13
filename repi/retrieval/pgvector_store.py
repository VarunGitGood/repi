from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional
from uuid import UUID
from sqlmodel import select, Session, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from repi.core.dates import DateHandler
from repi.models.schema import LogChunk
from repi.models.filters import RetrievalFilters
from repi.retrieval.filter_builder import build_filter_expressions
import numpy as np
import logging

logger = logging.getLogger(__name__)

class PgVectorStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, chunk_id: str, embedding: List[float], text: str, source_service: str,
                     source_env: str = "production", log_level: Optional[str] = None,
                     timestamp_start: Optional[datetime] = None, timestamp_end: Optional[datetime] = None,
                     log_metadata: Optional[Dict[str, Any]] = None,
                     signature: Optional[str] = None, project_id: Optional[UUID] = None) -> None:
        """Upsert a log chunk with its embedding and metadata."""
        # Check if exists
        statement = select(LogChunk).where(LogChunk.chunk_id == chunk_id)
        result = await self.session.exec(statement)
        chunk = result.one_or_none()
        
        # The log_chunks.timestamp_{start,end} columns are TIMESTAMPTZ and the
        # SQLModel declares DateTime(timezone=True). On a non-UTC host (e.g.
        # IST/+05:30), passing a naive datetime here causes SQLAlchemy/asyncpg
        # to interpret it as local time, silently shifting the stored value by
        # the offset. Attach UTC explicitly so the write lands at the intended
        # wall-clock UTC time regardless of host TZ.
        ts_start = DateHandler.to_aware_utc(timestamp_start)
        ts_end = DateHandler.to_aware_utc(timestamp_end)

        if chunk:
            chunk.embedding = embedding
            chunk.text = text
            chunk.source_service = source_service
            chunk.source_env = source_env
            chunk.log_level = log_level
            chunk.timestamp_start = ts_start
            chunk.timestamp_end = ts_end
            chunk.log_metadata = log_metadata
            chunk.signature = signature
            chunk.project_id = project_id
        else:
            chunk = LogChunk(
                chunk_id=chunk_id,
                embedding=embedding,
                text=text,
                source_service=source_service,
                source_env=source_env,
                log_level=log_level,
                timestamp_start=ts_start,
                timestamp_end=ts_end,
                log_metadata=log_metadata,
                signature=signature,
                project_id=project_id,
            )
            self.session.add(chunk)
        
        await self.session.commit()

    async def search(self, embedding: List[float], top_k: int = 5, 
                     filters: RetrievalFilters | None = None) -> List[Tuple[str, float]]:
        """
        Search for similar chunks using vector similarity and metadata filters.
        Using inner product similarity (<#>).
        """
        # pgvector <#> is negative inner product; max_inner_product() returns it pre-negated for ORDER BY ASC
        from sqlalchemy import func
        
        statement = select(LogChunk.chunk_id, (LogChunk.embedding.max_inner_product(embedding)).label("score"))
        
        logger.debug(f"PgVectorStore: Search request with top_k={top_k}, filters={filters}")
        
        if filters:
            exprs = build_filter_expressions(filters)
            if exprs:
                statement = statement.where(and_(*exprs))
                logger.debug(f"PgVectorStore: Applying filters: {filters}")
        
        statement = statement.order_by("score").limit(top_k)
        
        result = await self.session.exec(statement)
        rows = result.all()
        logger.debug(f"PgVectorStore: Found {len(rows)} matches")
        
        # score from max_inner_product is actually - (a . b)
        # We might want to return the actual inner product
        return [(row[0], -row[1]) for row in rows]

    async def filter_search(self, filters: RetrievalFilters | None, top_k: int = 10) -> List[Tuple[str, float]]:
        """Return chunks matching filters only, ordered by recency. Used when no semantic query is given."""
        statement = select(LogChunk.chunk_id)
        if filters:
            exprs = build_filter_expressions(filters)
            if exprs:
                statement = statement.where(and_(*exprs))
        statement = statement.order_by(LogChunk.timestamp_start.desc()).limit(top_k)
        result = await self.session.exec(statement)
        return [(row, 1.0) for row in result.all()]

    async def get_chunks_by_ids(self, chunk_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Retrieve chunks by their IDs."""
        statement = select(LogChunk).where(LogChunk.chunk_id.in_(chunk_ids))
        result = await self.session.exec(statement)
        chunks = result.all()
        return {c.chunk_id: c.model_dump(exclude={"embedding"}) for c in chunks}
