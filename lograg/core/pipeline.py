import json
from typing import List, Dict, Any, Optional
from lograg.ingest.parser import parse_log_line
from lograg.ingest.chunker import chunk_logs
from lograg.retrieval.bm25 import BM25Retriever
from lograg.retrieval.dense import DenseRetriever
from lograg.retrieval.rrf import rrf
from lograg.retrieval.reranker import CrossEncoderReranker
from lograg.llm.analyzer import LLMAnalyzer
from lograg.llm.schema import InvestigationResult
from lograg.storage.db import DatabaseManager

class LogRagPipeline:
    """
    Main pipeline orchestrating the log analysis process.
    """
    def __init__(self, db_manager: DatabaseManager, analyzer: LLMAnalyzer, reranker: Optional[CrossEncoderReranker] = None):
        self.db = db_manager
        self.analyzer = analyzer
        self.reranker = reranker or CrossEncoderReranker()

    def _stringify_chunk(self, chunk: Dict[str, Any]) -> str:
        """Convert a log cluster/chunk into a string for indexing."""
        return (
            f"Signature: {chunk['signature']}\n"
            f"Count: {chunk['count']}\n"
            f"Time Range: {chunk['time_range']}\n"
            f"Examples: {json.dumps(chunk['examples'])}"
        )

    def _format_cluster_for_reranking(self, cluster: Dict[str, Any]) -> str:
        """Format a log cluster into structured text for cross-encoder reranking."""
        examples_str = "\n".join(cluster['examples'])
        return (
            f"Signature: {cluster['signature']}\n"
            f"Count: {cluster['count']}\n"
            f"Time Range: {cluster['time_range']}\n"
            f"Examples:\n"
            f"{examples_str}"
        )

    def run_retrieval(self, query: str, chunks: List[Dict[str, Any]], mode: str = "rerank") -> List[str]:
        """
        Run only the retrieval part of the pipeline.
        
        Args:
            query: The search query.
            chunks: List of log clusters.
            mode: one of 'bm25', 'dense', 'hybrid', 'rerank'.
            
        Returns:
            List of ranked log signatures.
        """
        documents = [self._stringify_chunk(c) for c in chunks]
        if not documents:
            return []

        # 1. BM25 Search
        bm25_retriever = BM25Retriever(documents)
        if mode == "bm25":
            indices = bm25_retriever.search(query, top_k=len(documents))
            return [chunks[idx]["signature"] for idx in indices]

        # 2. Dense Search
        dense_retriever = DenseRetriever(documents)
        if mode == "dense":
            indices = dense_retriever.search(query, top_k=len(documents))
            return [chunks[idx]["signature"] for idx in indices]

        # 3. Hybrid (RRF)
        bm25_results = bm25_retriever.search(query, top_k=min(20, len(documents)))
        dense_results = dense_retriever.search(query, top_k=min(20, len(documents)))
        fused_indices = rrf([bm25_results, dense_results])
        
        if mode == "hybrid":
            return [chunks[idx]["signature"] for idx in fused_indices]

        # 4. Rerank
        candidate_indices = fused_indices[:20]
        candidate_clusters = [chunks[idx] for idx in candidate_indices]
        candidate_texts = [self._format_cluster_for_reranking(c) for c in candidate_clusters]
        
        reranked_indices = self.reranker.rerank(query, candidate_texts, top_k=len(candidate_indices))
        return [candidate_clusters[idx]["signature"] for idx in reranked_indices]

    def run_investigation(self, query: str, raw_logs: List[str], top_k: int = 5) -> InvestigationResult:
        """
        Run the complete investigation pipeline.
        
        Args:
            query: The investigation query.
            raw_logs: List of raw log strings.
            top_k: Number of log clusters to provide to the LLM.
            
        Returns:
            The InvestigationResult.
        """
        if not raw_logs:
            return InvestigationResult(
                title="No Logs Provided",
                summary="The input log list was empty.",
                root_cause="N/A",
                confidence=0.0,
                impact={"severity": "none", "description": "No logs to analyze"},
                affected_services=[],
                reproduction_steps=[],
                should_create_issue=False
            )

        # 1. Parse logs
        parsed_logs = [parse_log_line(line) for line in raw_logs]
        
        # 2. Chunk logs
        chunks = chunk_logs(parsed_logs)
        
        # 3. Build document list
        documents = [self._stringify_chunk(c) for c in chunks]
        
        if not documents:
            return InvestigationResult(
                title="No Log Clusters Found",
                summary="Logs were parsed but no meaningful clusters were formed.",
                root_cause="N/A",
                confidence=0.0,
                impact={"severity": "none", "description": "No clusters found"},
                affected_services=[],
                reproduction_steps=[],
                should_create_issue=False
            )

        # 4. Run retrieval
        bm25_retriever = BM25Retriever(documents)
        dense_retriever = DenseRetriever(documents)
        
        # Take top 10 from each for RRF
        bm25_results = bm25_retriever.search(query, top_k=min(10, len(documents)))
        dense_results = dense_retriever.search(query, top_k=min(10, len(documents)))
        
        # 5. Fuse results using RRF
        fused_indices = rrf([bm25_results, dense_results])
        
        # 6. Reranking Stage
        # Take top 20 candidates from RRF for reranking
        candidate_indices = fused_indices[:20]
        candidate_clusters = [chunks[idx] for idx in candidate_indices]
        candidate_texts = [self._format_cluster_for_reranking(c) for c in candidate_clusters]
        
        reranked_indices_within_candidates = self.reranker.rerank(query, candidate_texts, top_k=top_k)
        selected_clusters = [candidate_clusters[idx] for idx in reranked_indices_within_candidates]
        
        # 7. Call LLM analyzer
        result = self.analyzer.analyze(query, selected_clusters)
        
        # 8. Save to DB
        self.db.save_investigation(result)
        
        return result
