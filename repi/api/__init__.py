import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from repi.core.container import get_container
from repi.api.ingest import router as ingest_router
from repi.api.investigate import router as investigate_router
from repi.api.watchers import router as watchers_router

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

app.include_router(ingest_router, tags=["ingest"])
app.include_router(investigate_router, tags=["investigate"])
app.include_router(watchers_router, tags=["watchers"])


@app.get("/services", tags=["services"])
async def list_services():
    container = get_container()
    await container.init_known_services()
    return {"services": container.known_services}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
