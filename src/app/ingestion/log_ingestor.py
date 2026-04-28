from __future__ import annotations
import logging
from typing import List, Optional
from src.app.ingestion.log_parser import parse_log_line
from src.app.ingestion.log_chunker import chunk_logs
from src.app.retrieval.pgvector_store import PgVectorStore
import uuid

logger = logging.getLogger(__name__)

class LogIngestor:
    def __init__(self, vector_store: PgVectorStore, embedding_func) -> None:
        self.vector_store = vector_store
        self.embedding_func = embedding_func # Function that takes list of strings and returns embeddings

    async def ingest(self, logs: str | List[str], source_service: str, source_env: str = "production") -> int:
        """
        Ingest logs from a specific source.
        """
        if not source_service:
            raise ValueError("source_service is required")

        if isinstance(logs, str):
            lines = logs.strip().split("\n")
        else:
            lines = logs

        parsed_logs = [parse_log_line(line) for line in lines if line.strip()]
        chunks = chunk_logs(parsed_logs)

        # Prepare for vector store
        chunk_texts = [f"Signature: {c.signature}\nExamples: {' '.join(c.examples)}" for c in chunks]
        
        if not chunk_texts:
            return 0
            
        embeddings = self.embedding_func(chunk_texts)

        count = 0
        for i, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            
            await self.vector_store.upsert(
                chunk_id=chunk_id,
                embedding=embeddings[i].tolist() if hasattr(embeddings[i], 'tolist') else embeddings[i],
                text=chunk_texts[i],
                source_service=source_service,
                source_env=source_env,
                log_level=chunk.log_level,
                timestamp_start=chunk.timestamp_start,
                timestamp_end=chunk.timestamp_end
            )
            count += 1

        logger.info(f"Ingested {count} chunks from service {source_service}")
        return count
