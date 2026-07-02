import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from repi.api.limiter import limiter
from repi.api.guards import block_in_demo

from repi.core.container import get_container
from repi.api.ingest import router as ingest_router
from repi.api.investigate import router as investigate_router
from repi.api.watchers import router as watchers_router
from repi.api.config import router as config_router
from repi.api.chat import router as chat_router
from repi.api.conversations import router as conversations_router
from repi.api.projects import router as projects_router
from repi.api.leaderboard import router as leaderboard_router

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
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from repi.core.config import settings as _settings

_cors_origins = _settings.CORS_ORIGINS or [f"http://localhost:{_settings.UI_PORT}"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers fully disabled under the read-only demo lock (writes + admin/
# non-showcase reads). Showcase routers (investigate, chat, conversations,
# projects reads, services, leaderboard — all read-only) stay mounted; their
# per-route guards live inline.
_demo_locked = [Depends(block_in_demo)]
app.include_router(ingest_router, tags=["ingest"], dependencies=_demo_locked)
app.include_router(investigate_router, tags=["investigate"])
app.include_router(watchers_router, tags=["watchers"], dependencies=_demo_locked)
app.include_router(config_router, tags=["config"], dependencies=_demo_locked)
app.include_router(chat_router, tags=["chat"])
app.include_router(conversations_router, tags=["conversations"])
app.include_router(projects_router, tags=["projects"])
app.include_router(leaderboard_router, tags=["leaderboard"])


@app.get("/health", tags=["health"])
async def health():
    """Liveness + LLM-config probe. Always 200 once the API is up; the
    `llm_configured` flag tells clients whether /config setup is needed."""
    container = get_container()
    return {
        "status": "ok",
        "llm_configured": container.llm_provider is not None,
        "llm_init_error": container.llm_init_error,
    }


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
        await container.init_known_services()
        return {"services": [{"name": s, "env": "unknown", "enabled": True} for s in container.known_services]}
        
    return {"services": [{"name": c.service_name, "env": c.env, "enabled": c.enabled} for c in configs]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
