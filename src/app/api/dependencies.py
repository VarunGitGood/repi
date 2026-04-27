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
