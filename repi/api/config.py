import json
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from repi.core.config import settings, CONFIG_PATH

logger = logging.getLogger("repi.api.config")

router = APIRouter()

@router.get("/config")
async def get_config():
    """Return the current configuration."""
    return settings.model_dump()

@router.put("/config")
async def update_config(new_config: dict):
    """Update the configuration and save to config.json."""
    try:
        # Validate against Settings model
        from repi.core.config import Settings
        validated = Settings(**new_config)
        
        # Write to file
        with open(CONFIG_PATH, "w") as f:
            json.dump(validated.model_dump(), f, indent=2)
        
        # Hot reload
        settings.reload()
        
        return {"status": "success", "message": "Configuration updated and reloaded"}
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        raise HTTPException(status_code=400, detail=str(e))
