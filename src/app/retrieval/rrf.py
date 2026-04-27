from __future__ import annotations
from typing import List, Dict, Tuple, Any
from datetime import datetime
from src.app.retrieval.pgvector_store import PgVectorStore
from src.app.retrieval.pg_fts_retriever import PgFTSRetriever
from src.app.models.filters import RetrievalFilters
import logging

logger = logging.getLogger(__name__)

class RRFRetrievalService:
    def __init__(self, vector_store: PgVectorStore, fts_retriever: PgFTSRetriever, embedding_func) -> None:
        self.vector_store = vector_store
        self.fts_retriever = fts_retriever
        self.embedding_func = embedding_func

    async def search(self, query: str, top_k: int = 5, 
                     filters: RetrievalFilters | None = None, 
                     recency_boost: bool = False) -> List[Tuple[str, float]]:
        """
        Hybrid search using Vector and FTS with RRF fusion and optional recency boost.
        """
        logger.debug(f"RRF Search started: query='{query}', top_k={top_k}, filters={filters}")
        
        # 1. Generate embedding for query
        query_embedding = self.embedding_func([query])[0]
        if hasattr(query_embedding, 'tolist'):
            query_embedding = query_embedding.tolist()

        # 2. Get rankings (top 20 for fusion)
        vector_results = await self.vector_store.search(embedding=query_embedding, top_k=20, filters=filters)
        fts_results = await self.fts_retriever.search(query=query, top_k=20, filters=filters)
        
        logger.debug(f"Vector candidates: {len(vector_results)}, FTS candidates: {len(fts_results)}")

        # Rankings are lists of chunk_ids
        vector_ranking = [res[0] for res in vector_results]
        fts_ranking = [res[0] for res in fts_results]

        # 3. Fuse rankings
        rrf_scores = {}
        k = 60
        for rank, chunk_id in enumerate(vector_ranking):
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1.0 / (k + rank)
        for rank, chunk_id in enumerate(fts_ranking):
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1.0 / (k + rank)

        # 4. Apply recency boost if requested
        if recency_boost:
            logger.debug("Applying recency boost")
            now = datetime.utcnow()
            # Fetch chunks to get timestamp_end
            chunk_ids = list(rrf_scores.keys())
            chunks_data = await self.vector_store.get_chunks_by_ids(chunk_ids)
            
            for chunk_id, score in rrf_scores.items():
                chunk = chunks_data.get(chunk_id)
                if chunk and chunk.get("timestamp_end"):
                    ts_end = chunk["timestamp_end"]
                    if isinstance(ts_end, str):
                        ts_end = datetime.fromisoformat(ts_end.replace("Z", "+00:00"))
                    
                    age_hours = (now - ts_end).total_seconds() / 3600
                    recency_factor = 1.0 / (1.0 + 0.1 * age_hours)
                    rrf_scores[chunk_id] = score * recency_factor
                    logger.debug(f"Chunk {chunk_id}: score={score:.4f}, age_hours={age_hours:.2f}, factor={recency_factor:.4f}")

        # 5. Sort and return top_k
        final_ranking = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        logger.debug(f"RRF Search completed: returned {len(final_ranking)} chunks")
        return final_ranking
