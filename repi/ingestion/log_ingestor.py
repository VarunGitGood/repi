from __future__ import annotations
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional
from repi.ingestion.log_parser import parse_log_line
from repi.ingestion.log_chunker import chunk_logs
from repi.retrieval.pgvector_store import PgVectorStore
import uuid

logger = logging.getLogger(__name__)

@dataclass
class IngestStats:
    """Parse-quality report for one ingest call. A run with
    lines_with_timestamp == 0 means time filters will never match these logs —
    surface that to the caller instead of failing silently at query time."""
    chunk_count: int = 0
    lines_total: int = 0
    lines_with_timestamp: int = 0
    level_counts: dict[str, int] = field(default_factory=dict)

class LogIngestor:
    def __init__(self, vector_store: PgVectorStore, embedding_func) -> None:
        self.vector_store = vector_store
        self.embedding_func = embedding_func

    async def ingest(self, logs: str | List[str], source_service: str, source_env: str = "production") -> IngestStats:
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

        stats = IngestStats(
            lines_total=len(parsed_logs),
            lines_with_timestamp=sum(1 for p in parsed_logs if p.parsed_timestamp is not None),
            level_counts=dict(Counter(p.level for p in parsed_logs)),
        )

        chunk_texts = [f"Signature: {c.signature}\nExamples: {' '.join(c.examples)}" for c in chunks]

        if not chunk_texts:
            return stats

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

        stats.chunk_count = count
        if stats.lines_total and stats.lines_with_timestamp == 0:
            logger.warning(
                f"No timestamps parsed from any of {stats.lines_total} lines for "
                f"{source_service} — time-based filters will not match these chunks"
            )
        logger.info(f"Ingested {count} chunks from service {source_service}")
        return stats
