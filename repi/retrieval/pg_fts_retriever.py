from __future__ import annotations
from typing import List, Tuple
from sqlmodel import select, and_, text
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import func
from repi.models.schema import LogChunk
from repi.models.filters import RetrievalFilters
from repi.retrieval.filter_builder import build_filter_expressions
import logging

logger = logging.getLogger(__name__)


class PgFTSRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, query: str, top_k: int = 5,
                     filters: RetrievalFilters | None = None) -> List[Tuple[str, float]]:
        """Hybrid-search FTS leg.

        Uses `websearch_to_tsquery` so user-typed input (quoted phrases,
        `-negation`, `OR`) is accepted without raising syntax errors. Ranks
        against the stored weighted `text_tsv` column (see db/schema.sql) so
        a service-name hit edges out a body-only loose match.
        """
        ts_query = func.websearch_to_tsquery('english', query)
        rank = func.ts_rank(LogChunk.text_tsv, ts_query)

        where_exprs: list = []
        if filters:
            where_exprs.extend(build_filter_expressions(filters))
        where_exprs.append(LogChunk.text_tsv.op('@@')(ts_query))

        statement = (
            select(LogChunk.chunk_id, rank.label("score"))
            .where(and_(*where_exprs))
            .order_by(text("score DESC"))
            .limit(top_k)
        )

        logger.debug(f"PgFTSRetriever: websearch query='{query}' top_k={top_k}")
        result = await self.session.exec(statement)
        rows = result.all()
        logger.debug(f"PgFTSRetriever: Found {len(rows)} matches")

        return [(row[0], float(row[1])) for row in rows]
