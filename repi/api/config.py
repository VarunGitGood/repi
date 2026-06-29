import json
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from repi.core.config import settings, CONFIG_PATH, CONFIG_DIR
from repi.core.container import get_container

logger = logging.getLogger("repi.api.config")

router = APIRouter()


def _mask_secrets(data: dict) -> dict:
    masked = {}
    for key, value in data.items():
        if key.endswith(("_KEY", "_SECRET", "_TOKEN")) and value:
            s = str(value)
            masked[key] = f"{s[:4]}...{s[-4:]}" if len(s) > 10 else "***"
        else:
            masked[key] = value
    return masked


@router.get("/config")
async def get_config():
    """Return the current configuration with secrets masked."""
    return _mask_secrets(settings.model_dump())

@router.put("/config")
async def update_config(new_config: dict):
    """Merge `new_config` on top of the existing config.json and reload.

    Semantically a PATCH: a partial body (e.g. `{"MISTRAL_API_KEY": "..."}`)
    must not clobber unsent fields with their class defaults, which would
    break a running container instantly.
    """
    try:
        from repi.core.config import Settings

        existing: dict = {}
        if CONFIG_PATH.exists():
            try:
                existing = json.loads(CONFIG_PATH.read_text())
            except json.JSONDecodeError:
                existing = {}

        merged = {**existing, **new_config}
        validated = Settings(**merged)

        # Fail fast on an unknown EMBEDDING_BACKEND so we don't persist a
        # value that would 500 on first /ingest or /investigate.
        from repi.embeddings import create_embedder
        create_embedder(validated.EMBEDDING_BACKEND)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(validated.model_dump(), f, indent=2)

        settings.reload()
        get_container().refresh_llm()

        return {"status": "success", "message": "Configuration updated and reloaded"}
    except Exception as e:
        logger.error("Failed to update config", exc_info=True)
        raise HTTPException(status_code=400, detail="Configuration update failed")
