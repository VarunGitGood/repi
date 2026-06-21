from __future__ import annotations
from sqlmodel.ext.asyncio.session import AsyncSession


def create_fts_retriever(backend: str, session: AsyncSession):
    key = (backend or "").strip().lower()
    if key == "paradedb":
        from repi.retrieval.paradedb_retriever import ParadeDBRetriever
        return ParadeDBRetriever(session)
    if key in ("pg", "postgres", "tsvector"):
        from repi.retrieval.pg_fts_retriever import PgFTSRetriever
        return PgFTSRetriever(session)
    raise ValueError(
        f"Unknown FTS_BACKEND {backend!r}. Expected 'paradedb' or 'pg'."
    )
