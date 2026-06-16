import json
import logging
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from repi.core.config import settings, Settings, CONFIG_PATH, CONFIG_DIR
from repi.core.container import get_container

logger = logging.getLogger("repi.api.config")

router = APIRouter()


@router.get("/config")
async def get_config():
    """Return the current configuration."""
    return settings.model_dump()


@router.put("/config")
async def update_config(new_config: dict):
    """Merge `new_config` on top of the existing config.json and reload.

    Semantically a PATCH: a partial body (e.g. `{"MISTRAL_API_KEY": "..."}`)
    must not clobber unsent fields with their class defaults, which would
    break a running container instantly.
    """
    existing: dict = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            existing = {}

    merged = {**existing, **new_config}

    # Validation errors (bad field/value, e.g. LLM_MAX_CALLS_PER_MIN < 1) → 400
    try:
        validated = Settings(**merged)
    except ValidationError as e:
        logger.warning(f"Config validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # Invalid EMBEDDING_BACKEND is also a client error → 400
    try:
        from repi.embeddings import create_embedder
        create_embedder(validated.EMBEDDING_BACKEND)
    except Exception as e:
        logger.warning(f"Invalid EMBEDDING_BACKEND '{validated.EMBEDDING_BACKEND}': {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid EMBEDDING_BACKEND '{validated.EMBEDDING_BACKEND}': {e}",
        )

    # File write / reload failures are server-side → 500
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(validated.model_dump(), f, indent=2)

        settings.reload()
        get_container().refresh_llm()
    except Exception as e:
        logger.error(f"Failed to persist/reload config: {e}")
        raise HTTPException(status_code=500, detail="Failed to persist or reload configuration")

    return {"status": "success", "message": "Configuration updated and reloaded"}
