import json
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from repi.core.config import settings, CONFIG_PATH, CONFIG_DIR
from repi.core.container import get_container

logger = logging.getLogger("repi.api.config")

router = APIRouter()

@router.get("/config")
async def get_config():
    """Return the current configuration."""
    return settings.model_dump()

@router.put("/config")
async def update_config(new_config: dict):
    """Update the configuration and save to config.json.

    Merges `new_config` on top of the existing config.json (or class defaults
    if no file yet). A partial PUT — e.g. `{"MISTRAL_API_KEY": "sk-…"}` — must
    NOT clobber DATABASE_URL/REDIS_URL etc. with their localhost defaults,
    which would break the running app instantly under docker.
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

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(validated.model_dump(), f, indent=2)

        settings.reload()
        get_container().refresh_llm()

        return {"status": "success", "message": "Configuration updated and reloaded"}
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        raise HTTPException(status_code=400, detail=str(e))
