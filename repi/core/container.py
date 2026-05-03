import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from repi.core.config import settings
from repi.core.cache import cache
from repi.retrieval.pgvector_store import PgVectorStore
from repi.retrieval.pg_fts_retriever import PgFTSRetriever
from repi.retrieval.rrf import RRFRetrievalService
from repi.ingestion.log_ingestor import LogIngestor
from repi.llm.factory import create_provider_from_env
from repi.retrieval.query_expander import QueryExpander
from repi.investigation.react_loop import ReactInvestigationLoop
from repi.investigation.store import InvestigationStore
from repi.investigation.tools import (
    search_logs, get_timeline, find_co_occurring, get_service_summary, get_all_services
)
import asyncpg
from sentence_transformers import SentenceTransformer
from typing import Optional

# Configure logging based on settings
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
if os.getenv("ENV") == "dev":
    LOG_LEVEL = "DEBUG"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("src.app")

class Container:
    def __init__(self) -> None:
        self.db_url = settings.DATABASE_URL
        self.engine = create_async_engine(self.db_url, echo=False)
        self.async_session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.pool: Optional[asyncpg.Pool] = None
        
        # Load embedding model once
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.known_services: list[str] = []
        
        # LLM Foundation
        self.llm_provider = create_provider_from_env()
        self.query_expander = QueryExpander(llm=self.llm_provider)

    def embedding_func(self, texts: list[str]):
        return self.model.encode(texts, convert_to_numpy=True)

    def get_session(self):
        """Return an async context manager that yields a DB session."""
        return self.async_session_maker()

    async def init_db(self) -> None:
        """Initialize pgvector extension and create tables."""
        from sqlalchemy import text
        from repi.models.schema import LogChunk # Ensure models are registered
        
        async with self.engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            from sqlmodel import SQLModel
            await conn.run_sync(SQLModel.metadata.create_all)
            
        if not self.pool:
            dsn = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
            self.pool = await asyncpg.create_pool(dsn)
            
        # Initialize Cache
        await cache.connect()
        
        logger.info("Database and Cache initialized")

    async def init_known_services(self) -> list[str]:
        """Query distinct services from DB."""
        async with self.async_session_maker() as session:
            self.known_services = await get_all_services(self.pool)
            logger.info(f"Loaded known services: {self.known_services}")
        return self.known_services

    def get_ingestor(self, session: AsyncSession) -> LogIngestor:
        vector_store = PgVectorStore(session)
        return LogIngestor(vector_store, self.embedding_func)

    def get_retrieval_service(self, session: AsyncSession) -> RRFRetrievalService:
        vector_store = PgVectorStore(session)
        fts_retriever = PgFTSRetriever(session)
        return RRFRetrievalService(vector_store, fts_retriever, self.embedding_func)

    def get_investigation_loop(self, session: AsyncSession) -> ReactInvestigationLoop:
        """Create a ReAct loop with tools and persistence store."""
        retrieval_service = self.get_retrieval_service(session)
        store = InvestigationStore(session)
        
        # Wrapped tools with caching
        async def cached_search_logs(**kwargs):
            key = cache.make_key("search_logs", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await search_logs(retrieval_service, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        async def cached_service_summary(**kwargs):
            key = cache.make_key("get_service_summary", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await get_service_summary(self.pool, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        async def cached_find_co_occurring(**kwargs):
            key = cache.make_key("find_co_occurring", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await find_co_occurring(self.pool, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        tools = {
            "search_logs": cached_search_logs,
            "get_timeline": lambda **kwargs: get_timeline(self.pool, **kwargs),
            "find_co_occurring": cached_find_co_occurring,
            "get_service_summary": cached_service_summary,
        }
        
        return ReactInvestigationLoop(
            llm=self.llm_provider,
            tools=tools,
            known_services=self.known_services,
            store=store
        )

def get_container() -> Container:
    # Use global singleton pattern for API if needed, or just return instance
    if not hasattr(get_container, "_instance"):
        get_container._instance = Container()
    return get_container._instance
