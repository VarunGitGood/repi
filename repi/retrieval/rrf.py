from __future__ import annotations
from typing import List, Tuple
import asyncio
import logging

from repi.core.dates import default_date_handler as _dh
from repi.retrieval.pgvector_store import PgVectorStore
from repi.retrieval.pg_fts_retriever import PgFTSRetriever
from repi.retrieval.diversify import diversify_by_service
from repi.models.filters import RetrievalFilters

logger = logging.getLogger(__name__)


class RRFRetrievalService:
    """Hybrid search via Reciprocal Rank Fusion over pgvector + Postgres FTS.

    `per_query_fanout` caps how many rows each leg (vector / FTS) pulls per
    query variant before fusion. Plain RRF's recall is bounded by this number;
    raise it for harder corpora at the cost of more DB work.
    """

    DEFAULT_RRF_K = 60

    def __init__(
        self,
        vector_store: PgVectorStore,
        fts_retriever: PgFTSRetriever,
        embedding_func,
        per_query_fanout: int = 20,
    ) -> None:
        self.vector_store = vector_store
        self.fts_retriever = fts_retriever
        self.embedding_func = embedding_func
        self.per_query_fanout = per_query_fanout

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
        recency_boost: bool = False,
        expanded_queries: list[str] | None = None,
    ) -> List[Tuple[str, float]]:
        """Plain RRF (no diversification). Signature preserved for back-compat."""
        return await self._rrf(query, top_k, filters, recency_boost, expanded_queries)

    async def search_diverse(
        self,
        query: str,
        top_k: int = 5,
        filters: RetrievalFilters | None = None,
        recency_boost: bool = False,
        expanded_queries: list[str] | None = None,
        over_fetch: int = 3,
        cap_ratio: float = 0.4,
    ) -> List[Tuple[str, float]]:
        """RRF with service-stratified diversification.

        Over-fetches `top_k * over_fetch` from plain RRF, fetches each
        candidate's service, then reorders so no single service occupies more
        than `ceil(top_k * cap_ratio)` of the returned slice. Falls through to
        plain RRF order when the candidate pool is single-service.
        """
        pool_size = max(top_k, top_k * over_fetch)
        ranked = await self._rrf(query, pool_size, filters, recency_boost, expanded_queries)
        if not ranked:
            return ranked

        chunk_ids = [cid for cid, _ in ranked]
        meta = await self.vector_store.get_chunks_by_ids(chunk_ids)

        enriched = [
            {
                "chunk_id": cid,
                "score": score,
                "service": (meta.get(cid) or {}).get("source_service"),
            }
            for cid, score in ranked
        ]
        diversified = diversify_by_service(enriched, top_k=top_k, cap_ratio=cap_ratio)
        return [(c["chunk_id"], c["score"]) for c in diversified]

    async def _rrf(
        self,
        query: str,
        top_k: int,
        filters: RetrievalFilters | None,
        recency_boost: bool,
        expanded_queries: list[str] | None,
    ) -> List[Tuple[str, float]]:
        queries = [query]
        if expanded_queries:
            for eq in expanded_queries:
                if eq not in queries:
                    queries.append(eq)

        logger.debug(f"RRF Search started with {len(queries)} query variants")

        tasks = []
        for q in queries:
            q_emb = self.embedding_func([q])[0]
            if hasattr(q_emb, 'tolist'):
                q_emb = q_emb.tolist()
            tasks.append(self.vector_store.search(embedding=q_emb, top_k=self.per_query_fanout, filters=filters))
            tasks.append(self.fts_retriever.search(query=q, top_k=self.per_query_fanout, filters=filters))

        all_results = await asyncio.gather(*tasks)

        rrf_scores: dict[str, float] = {}
        for ranking_results in all_results:
            for rank, (chunk_id, _score) in enumerate(ranking_results):
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (self.DEFAULT_RRF_K + rank)

        if recency_boost:
            logger.debug("Applying recency boost")
            now = _dh.now()
            chunk_ids = list(rrf_scores.keys())
            chunks_data = await self.vector_store.get_chunks_by_ids(chunk_ids)

            for chunk_id, score in list(rrf_scores.items()):
                chunk = chunks_data.get(chunk_id)
                if chunk and chunk.get("timestamp_start"):
                    ts = chunk["timestamp_start"]
                    if isinstance(ts, str):
                        ts = _dh.parse_iso(ts)
                    age_hours = (now - ts).total_seconds() / 3600
                    recency_factor = 1.0 / (1.0 + 0.1 * max(0.0, age_hours))
                    rrf_scores[chunk_id] = score * recency_factor

        final_ranking = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        logger.debug(f"RRF Search completed: returned {len(final_ranking)} chunks")
        return final_ranking
