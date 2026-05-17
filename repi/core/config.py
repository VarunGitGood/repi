from __future__ import annotations
import os
import json
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

CONFIG_PATH = Path("config.json")

class Settings(BaseSettings):
    # ENV
    # "production" (default) → quiet CLI output, uvicorn log_level=warning, no reload.
    # "development" → verbose CLI output, uvicorn log_level=info, reload allowed.
    REPI_ENV: str = Field(default="production", description="Runtime environment")

    # DATABASE
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/lograg",
        description="Postgres connection string (asyncpg format)"
    )

    # REDIS
    REDIS_URL: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL"
    )
    ENABLE_REDIS_CACHE: bool = True
    REDIS_CACHE_TTL_SECONDS: int = 300
    EMBEDDING_CACHE_TTL_SECONDS: int = 3600

    # TIME WINDOWS
    # Starting window for investigation (minutes)
    TIME_WINDOW_INITIAL_MINUTES: int = 10
    # Comma-separated expansion windows — "60,360,1440" = 1h, 6h, 24h
    TIME_WINDOW_EXPANSIONS: str = "60,360,1440"

    # INVESTIGATION
    INVESTIGATION_TTL_MINUTES: int = 30
    AUTO_DELETE_OLD_INVESTIGATIONS: bool = False
    DELETE_AFTER_DAYS: int = 7

    # LLM & RETRY
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    MISTRAL_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # WORKER
    WATCHER_CONFIG_REFRESH_SECS: int = 30

    # WEB UI
    UI_PORT: int = 3000

    MAX_RETRIES_PER_STEP: int = 2
    BACKOFF_BASE_SECONDS: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def time_expansions_list(self) -> List[int]:
        return [int(x.strip()) for x in self.TIME_WINDOW_EXPANSIONS.split(",") if x.strip()]

    def reload(self):
        """Hot-reload settings from config.json."""
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
            except Exception as e:
                print(f"Error reloading config: {e}")

def get_settings() -> Settings:
    """Initialize settings, preferring config.json if it exists."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            return Settings(**data)
        except Exception as e:
            print(f"Error loading config.json: {e}")
    return Settings()

settings = get_settings()
