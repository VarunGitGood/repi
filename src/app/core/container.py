import os
import logging
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from src.app.retrieval.pgvector_store import PgVectorStore
from src.app.retrieval.pg_fts_retriever import PgFTSRetriever
from src.app.retrieval.rrf import RRFRetrievalService
from src.app.ingestion.log_ingestor import LogIngestor
from src.app.llm.factory import create_provider_from_env
from src.app.retrieval.query_expander import QueryExpander
from src.app.investigation.react_loop import ReactInvestigationLoop
from src.app.investigation.tools import search_logs, get_timeline, find_co_occurring, get_service_summary
from sentence_transformers import SentenceTransformer

# Load environment variables from .env
load_dotenv()

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ENV = os.getenv("ENV", "production").lower()

if ENV == "dev":
    LOG_LEVEL = "DEBUG"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("src.app")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

class Container:
    def __init__(self) -> None:
        self.db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/lograg")
        self.engine = create_async_engine(self.db_url, echo=False)
        self.async_session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        
        # Load embedding model once
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.known_services: list[str] = os.getenv("KNOWN_SERVICES", "").split(",")
        self.known_services = [s.strip() for s in self.known_services if s.strip()]
        
        # LLM Foundation
        self.llm_provider = create_provider_from_env()
        self.query_expander = QueryExpander(llm=self.llm_provider)

    def embedding_func(self, texts: list[str]):
        return self.model.encode(texts, convert_to_numpy=True)

    async def get_session(self) -> AsyncSession:
        async with self.async_session_maker() as session:
            yield session

    async def init_db(self) -> None:
        """Initialize pgvector extension and create tables."""
        from sqlalchemy import text
        from src.app.models.schema import LogChunk # Ensure model is registered
        
        async with self.engine.begin() as conn:
            # 1. Create extension
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # 2. Create tables
            from sqlmodel import SQLModel
            await conn.run_sync(SQLModel.metadata.create_all)
            
        logger.info("Database initialized (extension and tables verified)")

    async def init_known_services(self) -> None:
        """Query distinct services from DB if not provided via env."""
        if not self.known_services:
            from src.app.models.schema import LogChunk
            async with self.async_session_maker() as session:
                statement = select(LogChunk.source_service).distinct()
                result = await session.exec(statement)
                self.known_services = list(result.all())
                logger.info(f"Loaded known services from DB: {self.known_services}")

    def get_ingestor(self, session: AsyncSession) -> LogIngestor:
        vector_store = PgVectorStore(session)
        return LogIngestor(vector_store, self.embedding_func)

    def get_retrieval_service(self, session: AsyncSession) -> RRFRetrievalService:
        vector_store = PgVectorStore(session)
        fts_retriever = PgFTSRetriever(session)
        return RRFRetrievalService(vector_store, fts_retriever, self.embedding_func)

    def get_investigation_loop(self, session: AsyncSession) -> ReactInvestigationLoop:
        """
        Create a ReAct loop with tools bound to the current session.
        """
        vector_store = PgVectorStore(session)
        retrieval_service = self.get_retrieval_service(session)
        
        # Bind tools to dependencies
        tools = {
            "search_logs": lambda **kwargs: search_logs(retrieval_service, **kwargs),
            "get_timeline": lambda **kwargs: get_timeline(vector_store, **kwargs),
            "find_co_occurring": lambda **kwargs: find_co_occurring(vector_store, **kwargs),
            "get_service_summary": lambda **kwargs: get_service_summary(vector_store, **kwargs),
        }
        
        return ReactInvestigationLoop(
            llm=self.llm_provider,
            tools=tools,
            known_services=self.known_services
        )
