from __future__ import annotations
from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from src.app.core.container import Container
from src.app.ingestion.log_ingestor import LogIngestor

container = Container()

async def get_session() -> AsyncSession:
    async with container.async_session_maker() as session:
        yield session

async def get_ingestor(session: AsyncSession = Depends(get_session)) -> LogIngestor:
    return container.get_ingestor(session)

def get_container() -> Container:
    return container

async def get_retrieval_service(session: AsyncSession = Depends(get_session)):
    return container.get_retrieval_service(session)

async def get_investigation_loop(session: AsyncSession = Depends(get_session)):
    return container.get_investigation_loop(session)
