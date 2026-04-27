from __future__ import annotations
from typing import List, Tuple, Any
from sqlmodel import select, and_, func, text
from sqlmodel.ext.asyncio.session import AsyncSession
from src.app.models.schema import LogChunk
from src.app.models.filters import RetrievalFilters
from src.app.retrieval.filter_builder import build_filter_expressions

class PgFTSRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, query: str, top_k: int = 5, 
                     filters: RetrievalFilters | None = None) -> List[Tuple[str, float]]:
        """
        Search for logs using Postgres Full-Text Search.
        Uses ts_rank for scoring.
        """
        # score = ts_rank(to_tsvector('english', text), plainto_tsquery('english', query))
        
        from sqlalchemy import func, literal_column
        
        # We need to use text() or func for ts_rank since it's Postgres specific
        ts_vector = func.to_tsvector('english', LogChunk.text)
        ts_query = func.plainto_tsquery('english', query)
        rank = func.ts_rank(ts_vector, ts_query)
        
        statement = select(LogChunk.chunk_id, rank.label("score"))
        
        # Apply filters
        where_exprs = []
        if filters:
            where_exprs.extend(build_filter_expressions(filters))
            
        # Also filter by matching the query
        where_exprs.append(ts_vector.op('@@')(ts_query))
        
        statement = statement.where(and_(*where_exprs))
        statement = statement.order_by(text("score DESC")).limit(top_k)
        
        result = await self.session.exec(statement)
        return [(row[0], float(row[1])) for row in result.all()]
