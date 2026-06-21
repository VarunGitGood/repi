from __future__ import annotations
from typing import List, Tuple
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text as sa_text
from repi.models.filters import RetrievalFilters
from repi.retrieval.filter_builder import build_filter_expressions
import logging

logger = logging.getLogger(__name__)


class ParadeDBRetriever:
    """BM25 full-text search via ParadeDB's pg_search extension.

    Drop-in replacement for PgFTSRetriever. Uses the ``|||`` (disjunction)
    operator against the ``log_chunks_bm25_idx`` BM25 index and
    ``pdb.score(id)`` for relevance ranking.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> List[Tuple[str, float]]:
        if not query or not query.strip():
            return []

        where_parts: list[str] = ["text ||| :query"]
        params: dict = {"query": query, "top_k": top_k}

        if filters:
            if filters.source_service:
                where_parts.append("source_service = :svc")
                params["svc"] = filters.source_service
            if filters.source_env:
                where_parts.append("source_env = :env")
                params["env"] = filters.source_env
            if filters.log_level:
                if isinstance(filters.log_level, (list, tuple, set)):
                    levels = [str(l).upper() for l in filters.log_level if l]
                    if len(levels) == 1:
                        where_parts.append("log_level = :lvl")
                        params["lvl"] = levels[0]
                    elif levels:
                        where_parts.append("log_level = ANY(:lvls)")
                        params["lvls"] = levels
                else:
                    where_parts.append("log_level = :lvl")
                    params["lvl"] = str(filters.log_level).upper()
            if filters.time_from:
                from repi.core.dates import DateHandler
                where_parts.append("timestamp_start >= :tfrom")
                params["tfrom"] = DateHandler.to_aware_utc(filters.time_from)
            if filters.time_to:
                from repi.core.dates import DateHandler
                where_parts.append("timestamp_end <= :tto")
                params["tto"] = DateHandler.to_aware_utc(filters.time_to)
            if filters.project_id:
                where_parts.append("project_id = :pid")
                params["pid"] = filters.project_id

        where_clause = " AND ".join(where_parts)
        sql = sa_text(
            f"SELECT chunk_id, pdb.score(id) AS score "
            f"FROM log_chunks "
            f"WHERE {where_clause} "
            f"ORDER BY score DESC "
            f"LIMIT :top_k"
        )

        logger.debug("ParadeDBRetriever: query=%r top_k=%d", query, top_k)
        result = await self.session.exec(sql, params=params)
        rows = result.all()
        logger.debug("ParadeDBRetriever: found %d matches", len(rows))

        return [(row[0], float(row[1])) for row in rows]
