import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from repi.core.config import settings

try:
    create_async_engine = importlib.import_module("sqlalchemy.ext.asyncio").create_async_engine
except ImportError as e:
    raise RuntimeError(
        "sqlalchemy.ext.asyncio is required for async DB support. "
        "Install SQLAlchemy>=1.4."
    ) from e
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
    search_logs, get_timeline, scan_window, get_service_summary, get_all_services, find_logs_by_id
)
from repi.embeddings import Embedder, create_embedder
import asyncpg
from typing import Optional

_log_level = settings.LOG_LEVEL.upper()
if settings.REPI_ENV.lower() == "development":
    _log_level = "DEBUG"

logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
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

        # Embedder load is deferred so /health and /config answer in <1s.
        self._embedder: Optional[Embedder] = None
        self.known_services: list[str] = []

        # LLM init is best-effort: a fresh install has no API key, but the
        # API still needs to boot so the user can POST /config. Routes that
        # need the LLM call require_llm() and 409 if it's still missing.
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
    def embedder(self) -> Embedder:
        # Rebuild if the configured backend changed (PUT /config can flip it
        # at runtime via settings.reload()).
        configured = (settings.EMBEDDING_BACKEND or "").strip().lower()
        if self._embedder is None or self._embedder.name != configured:
            self._embedder = create_embedder(configured)
        return self._embedder

    def embedding_func(self, texts: list[str]):
        return self.embedder.embed(texts)

    def get_session(self):
        """Return an async context manager that yields a DB session."""
        return self.async_session_maker()

    async def init_db(self) -> None:
        """Apply db/schema.sql (idempotent) and open the connection pool."""
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

    async def get_known_services(self, project_id=None) -> list[str]:
        """Project-scoped service list. Falls back to the global cached list
        when no project is given. Queried per call — DISTINCT on an indexed
        column; freshness matters more than the microseconds."""
        if project_id is None:
            return self.known_services
        services = await get_all_services(self.pool, project_id=project_id)
        async with self.async_session_maker() as session:
            from repi.models.schema import WatcherConfig
            stmt = select(WatcherConfig.service_name).where(
                WatcherConfig.enabled == True, WatcherConfig.project_id == project_id
            )
            res = await session.exec(stmt)
            for name in res.all():
                if name not in services:
                    services.append(name)
        return services

    def get_ingestor(self, session: AsyncSession) -> LogIngestor:
        vector_store = PgVectorStore(session)
        return LogIngestor(vector_store, self.embedding_func)

    def get_retrieval_service(self, session: AsyncSession) -> RRFRetrievalService:
        vector_store = PgVectorStore(session)
        fts_retriever = PgFTSRetriever(session)
        return RRFRetrievalService(vector_store, fts_retriever, self.embedding_func)

    def get_investigation_loop(self, session: AsyncSession, project_id=None,
                               known_services: list[str] | None = None) -> ReactInvestigationLoop:
        """Create a ReAct loop with tools and persistence store.

        `project_id` scopes every tool to one project. It is injected here in
        the tool closures — the LLM never sees (or controls) it, and the
        cache key includes it so two projects can't share cached results.
        """
        llm = self.require_llm()
        retrieval_service = self.get_retrieval_service(session)
        store = InvestigationStore(session)

        def scoped(kwargs: dict) -> dict:
            if project_id is not None:
                kwargs.setdefault("project_id", project_id)
            return kwargs

        async def cached_search_logs(**kwargs):
            kwargs = scoped(kwargs)
            key = cache.make_key("search_logs", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await search_logs(retrieval_service, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        async def cached_service_summary(**kwargs):
            kwargs = scoped(kwargs)
            key = cache.make_key("get_service_summary", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await get_service_summary(self.pool, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        async def cached_scan_window(**kwargs):
            kwargs = scoped(kwargs)
            key = cache.make_key("scan_window", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await scan_window(self.pool, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        async def cached_find_logs_by_id(**kwargs):
            kwargs = scoped(kwargs)
            key = cache.make_key("find_logs_by_id", **kwargs)
            hit = await cache.get(key)
            if hit: return hit
            res = await find_logs_by_id(self.pool, **kwargs)
            await cache.set(key, res, ttl=settings.REDIS_CACHE_TTL_SECONDS)
            return res

        tools = {
            "search_logs": cached_search_logs,
            "get_timeline": lambda **kwargs: get_timeline(self.pool, **scoped(kwargs)),
            "scan_window": cached_scan_window,
            "get_service_summary": cached_service_summary,
            "find_logs_by_id": cached_find_logs_by_id,
        }

        return ReactInvestigationLoop(
            llm=llm,
            tools=tools,
            known_services=known_services if known_services is not None else self.known_services,
            pool=self.pool,
            store=store,
            enable_reflection=settings.ENABLE_REFLECTION,
            reflection_interval=settings.REFLECTION_INTERVAL,
            llm_max_calls_per_min=settings.LLM_MAX_CALLS_PER_MIN,  

        )

    def get_investigation_store(self, session: AsyncSession) -> InvestigationStore:
        return InvestigationStore(session)

def get_container() -> Container:
    if not hasattr(get_container, "_instance"):
        get_container._instance = Container()
    return get_container._instance
