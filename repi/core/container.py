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
from repi.llm.provider import LLMProvider
from repi.retrieval.query_expander import QueryExpander
from repi.investigation.react_loop import ReactInvestigationLoop
from repi.investigation.store import InvestigationStore
from repi.investigation.tools import (
    search_logs, get_timeline, scan_window, get_service_summary, get_all_services
)
import asyncpg
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

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

        # SentenceTransformer load takes ~10s (importing torch + transformers,
        # then loading the model file). Defer the whole thing so startup stays
        # fast — /health and /config answer in <1s, the model is only paid for
        # on first /ingest or /investigate.
        self._model: Optional["SentenceTransformer"] = None
        self.known_services: list[str] = []

        # LLM init is *lazy*: a fresh install has no API key, but the API still
        # needs to boot so the user can POST /config. Routes that actually need
        # the LLM call require_llm() and surface a 409 if it's still missing.
        self.llm_provider: Optional[LLMProvider] = None
        self.query_expander: Optional[QueryExpander] = None
        self.llm_init_error: Optional[str] = None
        self._init_llm()

    def _init_llm(self) -> None:
        try:
            self.llm_provider = create_provider_from_env()
            self.query_expander = QueryExpander(llm=self.llm_provider)
            self.llm_init_error = None
            logger.info(f"LLM provider initialized: {settings.LLM_PROVIDER}")
        except Exception as e:
            self.llm_provider = None
            self.query_expander = None
            self.llm_init_error = str(e)
            logger.warning(
                f"LLM provider not configured ({e}); investigation routes will "
                "return 409 until POST /config supplies credentials."
            )

    def refresh_llm(self) -> None:
        """Re-attempt LLM init after /config has been updated."""
        self._init_llm()

    def require_llm(self) -> "LLMProvider":
        if self.llm_provider is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=409,
                detail=(
                    "LLM provider is not configured. "
                    "POST /config with your provider + API key first. "
                    f"(reason: {self.llm_init_error or 'no credentials'})"
                ),
            )
        return self.llm_provider

    @property
    def model(self) -> "SentenceTransformer":
        if self._model is None:
            logger.info("Loading SentenceTransformer (first use) …")
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def embedding_func(self, texts: list[str]):
        return self.model.encode(texts, convert_to_numpy=True)

    def get_session(self):
        """Return an async context manager that yields a DB session."""
        return self.async_session_maker()

    async def init_db(self) -> None:
        """Apply db/schema.sql then open the connection pool.

        asyncpg executes the full file natively — no statement splitting needed.
        Every statement in schema.sql is idempotent (IF NOT EXISTS), so this is
        safe to run on every startup.
        """
        import pathlib

        schema_file = pathlib.Path(__file__).resolve().parent.parent.parent / "db" / "schema.sql"
        sql = schema_file.read_text()

        dsn = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

        if not self.pool:
            self.pool = await asyncpg.create_pool(dsn)

        await cache.connect()
        logger.info("Database initialized")

    async def init_known_services(self) -> list[str]:
        """Query services from watcher_configs, fallback to log_chunks."""
        async with self.async_session_maker() as session:
            from repi.models.schema import WatcherConfig
            stmt = select(WatcherConfig.service_name).where(WatcherConfig.enabled == True)
            res = await session.exec(stmt)
            services = list(res.all())
            
            if not services:
                services = await get_all_services(self.pool)
            
            self.known_services = services
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
        llm = self.require_llm()
        retrieval_service = self.get_retrieval_service(session)
        store = InvestigationStore(session)

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

        async def cached_scan_window(**kwargs):
            key = cache.make_key("scan_window", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await scan_window(self.pool, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        tools = {
            "search_logs": cached_search_logs,
            "get_timeline": lambda **kwargs: get_timeline(self.pool, **kwargs),
            "scan_window": cached_scan_window,
            "get_service_summary": cached_service_summary,
        }
        
        return ReactInvestigationLoop(
            llm=llm,
            tools=tools,
            known_services=self.known_services,
            pool=self.pool,
            store=store,
            enable_reflection=settings.ENABLE_REFLECTION,
            reflection_interval=settings.REFLECTION_INTERVAL,
        )

    def get_investigation_store(self, session: AsyncSession) -> InvestigationStore:
        return InvestigationStore(session)

def get_container() -> Container:
    if not hasattr(get_container, "_instance"):
        get_container._instance = Container()
    return get_container._instance
