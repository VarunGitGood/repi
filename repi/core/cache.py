from __future__ import annotations
import json
import logging
import hashlib
import pickle
import redis.asyncio as redis
from typing import Any, Optional
from repi.core.config import settings

logger = logging.getLogger(__name__)

class RedisCacheService:
    def __init__(self):
        self.enabled = settings.ENABLE_REDIS_CACHE
        self.redis_url = settings.REDIS_URL
        self.client: Optional[redis.Redis] = None
        self._connected = False

    async def connect(self):
        if not self.enabled:
            return
        try:
            self.client = redis.from_url(self.redis_url)
            # Use a ping to verify connection
            await self.client.ping()
            self._connected = True
            logger.info(f"Connected to Redis at {self.redis_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Caching will be disabled.")
            self._connected = False

    async def get(self, key: str) -> Optional[Any]:
        if not self._connected or not self.client:
            return None
        try:
            data = await self.client.get(key)
            if data:
                return pickle.loads(data)
        except Exception as e:
            logger.warning(f"Redis GET error: {e}")
        return None

    async def set(self, key: str, value: Any, ttl: int = 300):
        if not self._connected or not self.client:
            return
        try:
            data = pickle.dumps(value)
            await self.client.set(key, data, ex=ttl)
        except Exception as e:
            logger.warning(f"Redis SET error: {e}")

    def make_key(self, tool_name: str, **kwargs) -> str:
        """Create a stable cache key based on tool name and arguments."""
        # Sort kwargs to ensure deterministic key
        sorted_args = json.dumps(kwargs, sort_keys=True, default=str)
        arg_hash = hashlib.md5(sorted_args.encode()).hexdigest()
        return f"repi:tool:{tool_name}:{arg_hash}"

    def make_embedding_key(self, text: str) -> str:
        text_hash = hashlib.md5(text.encode()).hexdigest()
        return f"repi:embed:{text_hash}"

# Global instance for easy access
cache = RedisCacheService()
