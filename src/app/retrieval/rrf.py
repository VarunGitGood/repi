from __future__ import annotations
from typing import List, Dict, Tuple, Any
from datetime import datetime
from src.app.retrieval.pgvector_store import PgVectorStore
from src.app.retrieval.pg_fts_retriever import PgFTSRetriever
from src.app.models.filters import RetrievalFilters
import logging
import asyncio

logger = logging.getLogger(__name__)

class RRFRetrievalService:
    def __init__(self, vector_store: PgVectorStore, fts_retriever: PgFTSRetriever, embedding_func) -> None:
        self.vector_store = vector_store
        self.fts_retriever = fts_retriever
        self.embedding_func = embedding_func

    async def search(self, query: str, top_k: int = 5, 
                     filters: RetrievalFilters | None = None, 
                     recency_boost: bool = False,
                     expanded_queries: list[str] | None = None) -> List[Tuple[str, float]]:
        """
        Hybrid search using Vector and FTS with RRF fusion and optional recency boost.
        Supports multiple query variants for broader coverage.
        """
        queries = [query]
        if expanded_queries:
            for eq in expanded_queries:
                if eq not in queries:
                    queries.append(eq)
        
        logger.debug(f"RRF Search started with {len(queries)} query variants")

        # Gather all rankings
        tasks = []
        for q in queries:
            # Generate embedding for each query variant
            q_emb = self.embedding_func([q])[0]
            if hasattr(q_emb, 'tolist'):
                q_emb = q_emb.tolist()
            
            tasks.append(self.vector_store.search(embedding=q_emb, top_k=20, filters=filters))
            tasks.append(self.fts_retriever.search(query=q, top_k=20, filters=filters))
        
        all_results = await asyncio.gather(*tasks)
        
        # 3. Fuse rankings (RRF)
        rrf_scores = {}
        k = 60
        for ranking_results in all_results:
            ranking = [res[0] for res in ranking_results]
            for rank, chunk_id in enumerate(ranking):
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1.0 / (k + rank)

        # 4. Apply recency boost if requested
        if recency_boost:
            logger.debug("Applying recency boost")
            now = datetime.utcnow()
            chunk_ids = list(rrf_scores.keys())
            chunks_data = await self.vector_store.get_chunks_by_ids(chunk_ids)
            
            for chunk_id, score in rrf_scores.items():
                chunk = chunks_data.get(chunk_id)
                if chunk and chunk.get("timestamp_start"):
                    ts = chunk["timestamp_start"]
                    if isinstance(ts, str):
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    
                    age_hours = (now - ts).total_seconds() / 3600
                    recency_factor = 1.0 / (1.0 + 0.1 * max(0, age_hours))
                    rrf_scores[chunk_id] = score * recency_factor
                    logger.debug(f"Chunk {chunk_id}: score={score:.4f}, age_hours={age_hours:.2f}, factor={recency_factor:.4f}")

        # 5. Sort and return top_k
        final_ranking = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        logger.debug(f"RRF Search completed: returned {len(final_ranking)} chunks")
        return final_ranking
