from __future__ import annotations
from fastapi import FastAPI, Depends
from src.app.api.ingest import router as ingest_router
from src.app.api.investigate import router as investigate_router
from src.app.api.dependencies import container
from sqlmodel.ext.asyncio.session import AsyncSession

app = FastAPI(title="LogRag API")

app.include_router(ingest_router)
app.include_router(investigate_router, prefix="/api/v1")

@app.on_event("startup")
async def startup_event():
    await container.init_db()
    await container.init_known_services()

# Dependency for LogIngestor
async def get_ingestor(session: AsyncSession = Depends(container.get_session)):
    return container.get_ingestor(session)

# Overriding the Depends(LogIngestor) in router needs some work or we use a different pattern.
# For now, let's keep it simple.
