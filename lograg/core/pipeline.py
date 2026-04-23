import json
from typing import List, Dict, Any
from lograg.ingest.parser import parse_log_line
from lograg.ingest.chunker import chunk_logs
from lograg.retrieval.bm25 import BM25Retriever
from lograg.retrieval.dense import DenseRetriever
from lograg.retrieval.rrf import rrf
from lograg.llm.analyzer import LLMAnalyzer
from lograg.llm.schema import InvestigationResult
from lograg.storage.db import DatabaseManager

class LogRagPipeline:
    """
    Main pipeline orchestrating the log analysis process.
    """
    def __init__(self, db_manager: DatabaseManager, analyzer: LLMAnalyzer):
        self.db = db_manager
        self.analyzer = analyzer

    def _stringify_chunk(self, chunk: Dict[str, Any]) -> str:
        """Convert a log cluster/chunk into a string for indexing."""
        return (
            f"Signature: {chunk['signature']}\n"
            f"Count: {chunk['count']}\n"
            f"Time Range: {chunk['time_range']}\n"
            f"Examples: {json.dumps(chunk['examples'])}"
        )

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
        
        bm25_results = bm25_retriever.search(query, top_k=min(10, len(documents)))
        dense_results = dense_retriever.search(query, top_k=min(10, len(documents)))
        
        # 5. Fuse results using RRF
        fused_indices = rrf([bm25_results, dense_results])
        
        # 6. Select top_k chunks
        selected_clusters = [chunks[idx] for idx in fused_indices[:top_k]]
        
        # 7. Call LLM analyzer
        result = self.analyzer.analyze(query, selected_clusters)
        
        # 8. Save to DB
        self.db.save_investigation(result)
        
        return result
