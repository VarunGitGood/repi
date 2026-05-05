import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from repi.core.container import get_container
from repi.api.ingest import router as ingest_router
from repi.api.investigate import router as investigate_router
from repi.api.watchers import router as watchers_router
from repi.api.config import router as config_router

logger = logging.getLogger("repi.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = get_container()
    await container.init_db()
    await container.init_known_services()
    yield


app = FastAPI(
    title="repi API",
    description="Log Investigation Engine API",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to the frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router, tags=["ingest"])
app.include_router(investigate_router, tags=["investigate"])
app.include_router(watchers_router, tags=["watchers"])
app.include_router(config_router, tags=["config"])


@app.get("/services", tags=["services"])
async def list_services():
    container = get_container()
    async with container.async_session_maker() as session:
        from repi.models.schema import WatcherConfig
        from sqlmodel import select
        stmt = select(WatcherConfig)
        res = await session.exec(stmt)
        configs = list(res.all())
    
    if not configs:
        # Fallback to names from log_chunks if no configs
        await container.init_known_services()
        return {"services": [{"name": s, "env": "unknown", "enabled": True} for s in container.known_services]}
        
    return {"services": [{"name": c.service_name, "env": c.env, "enabled": c.enabled} for c in configs]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
