from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional
from sqlmodel import select, Session, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from src.app.models.schema import LogChunk
from src.app.models.filters import RetrievalFilters
from src.app.retrieval.filter_builder import build_filter_expressions, _to_naive_utc
import numpy as np
import logging

logger = logging.getLogger(__name__)

class PgVectorStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, chunk_id: str, embedding: List[float], text: str, source_service: str, 
                     source_env: str = "production", log_level: Optional[str] = None, 
                     timestamp_start: Optional[datetime] = None, timestamp_end: Optional[datetime] = None,
                     log_metadata: Optional[Dict[str, Any]] = None) -> None:
        """Upsert a log chunk with its embedding and metadata."""
        # Check if exists
        statement = select(LogChunk).where(LogChunk.chunk_id == chunk_id)
        result = await self.session.exec(statement)
        chunk = result.one_or_none()
        
        if chunk:
            chunk.embedding = embedding
            chunk.text = text
            chunk.source_service = source_service
            chunk.source_env = source_env
            chunk.log_level = log_level
            chunk.timestamp_start = _to_naive_utc(timestamp_start)
            chunk.timestamp_end = _to_naive_utc(timestamp_end)
            chunk.log_metadata = log_metadata
        else:
            chunk = LogChunk(
                chunk_id=chunk_id,
                embedding=embedding,
                text=text,
                source_service=source_service,
                source_env=source_env,
                log_level=log_level,
                timestamp_start=_to_naive_utc(timestamp_start),
                timestamp_end=_to_naive_utc(timestamp_end),
                log_metadata=log_metadata
            )
            self.session.add(chunk)
        
        await self.session.commit()

    async def search(self, embedding: List[float], top_k: int = 5, 
                     filters: RetrievalFilters | None = None) -> List[Tuple[str, float]]:
        """
        Search for similar chunks using vector similarity and metadata filters.
        Using inner product similarity (<#>).
        """
        # In pgvector <#> is negative inner product, so lower is better for inner product
        # but for select we want to order by it.
        # However, the user said "Use embedding <#> $1 operator (inner product) for similarity"
        # and "Return (chunk_id, score) tuples".
        
        # SQLModel/SQLAlchemy doesn't have a direct operator for <#> in the standard DSL,
        # but we can use .op() or sa.func.
        # Actually pgvector-python provides a .l2_distance() etc.
        # For inner product, it's .max_inner_product().
        
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

    async def get_chunks_by_ids(self, chunk_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Retrieve chunks by their IDs."""
        statement = select(LogChunk).where(LogChunk.chunk_id.in_(chunk_ids))
        result = await self.session.exec(statement)
        chunks = result.all()
        return {c.chunk_id: c.model_dump() for c in chunks}
