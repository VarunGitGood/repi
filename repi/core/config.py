from __future__ import annotations
import os
import json
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic import Field

def _resolve_config_path() -> Path:
    """Locate .repi/config.json: cwd first (docker runs from /app), then parent
    directories (running from a subdir of a checkout), then alongside the
    package (where `repi init` writes it). Falls back to the cwd-relative
    default so a fresh PUT /config can still create the file."""
    rel = Path(".repi") / "config.json"
    for base in [Path.cwd(), *Path.cwd().parents]:
        candidate = base / rel
        if candidate.exists():
            return candidate
    pkg_anchored = Path(__file__).resolve().parent.parent.parent / rel
    if pkg_anchored.exists():
        return pkg_anchored
    return rel

CONFIG_PATH = _resolve_config_path()
CONFIG_DIR = CONFIG_PATH.parent

class Settings(BaseSettings):
    REPI_ENV: str = Field(default="production", description="Runtime environment")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level (DEBUG/INFO/WARNING/ERROR)")

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://repi_user:password_here@localhost:5432/repi",
        description="Postgres connection string (asyncpg format)"
    )

    REDIS_URL: str = Field(default="redis://localhost:6379")
    ENABLE_REDIS_CACHE: bool = True
    REDIS_CACHE_TTL_SECONDS: int = 300
    EMBEDDING_CACHE_TTL_SECONDS: int = 3600

    TIME_WINDOW_INITIAL_MINUTES: int = 10
    # Comma-separated expansion windows in minutes; "60,360,1440" = 1h, 6h, 24h.
    TIME_WINDOW_EXPANSIONS: str = "60,360,1440"

    INVESTIGATION_TTL_MINUTES: int = 30
    AUTO_DELETE_OLD_INVESTIGATIONS: bool = False
    DELETE_AFTER_DAYS: int = 7

    LLM_PROVIDER: str = "openai"
    LLM_MODEL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    MISTRAL_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    WATCHER_CONFIG_REFRESH_SECS: int = 30
    LLM_MAX_CALLS_PER_MIN: int = Field(default=60, ge=1)

    # "fastembed" (ONNX Runtime, ~50 MB) or "torch" via sentence-transformers
    # (~790 MB). Vectors are byte-identical; the choice is image size / RSS.
    # Additional options: "nomic" (768d), "bge" (384d).
    EMBEDDING_BACKEND: str = "fastembed"

    # "paradedb" (BM25 via pg_search) or "pg" (PostgreSQL tsvector).
    FTS_BACKEND: str = "paradedb"

    ENABLE_LEVEL_BOOST: bool = True

    UI_PORT: int = 3000

    MAX_RETRIES_PER_STEP: int = 2
    BACKOFF_BASE_SECONDS: int = 5

    # Forced re-plan turn every N action steps to break perseveration.
    ENABLE_REFLECTION: bool = True
    REFLECTION_INTERVAL: int = 3

    # /chat followup-bias envelope. When a turn omits an explicit time
    # window AND the previous assistant turn cited chunks, the chat path
    # widens the previous turn's first/last timestamps by this much on
    # each side. Same conceptual dial as TIME_WINDOW_INITIAL_MINUTES — kept
    # separate because the followup window is much narrower than a fresh
    # search and operators want to tune them independently.
    FOLLOWUP_BIAS_WINDOW_MINUTES: int = 5

    # Extra entity-detection regex patterns. Industry-standard IDs (UUID, W3C
    # trace/span ids, ULID, Stripe/Twilio-style prefixed ids, AWS resource ids,
    # git SHAs, hyphenated IDs containing a digit) are matched out of the box
    # by `repi.intent.resolver`. Use this to add organisation-specific shapes
    # (e.g. an HDFS shop adds r"\bblk_-?\d+\b"; a Stripe-internal logger adds
    # r"\bach_[A-Za-z0-9]{16,}\b"). Each entry is compiled with re.IGNORECASE.
    ENTITY_REGEX_EXTRA: List[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        # config.json is the sole source: dropping env/dotenv/secrets prevents
        # a stray shell var from silently flowing into the running app.
        return (init_settings,)

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
