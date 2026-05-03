from __future__ import annotations
import httpx
import json
import logging
from typing import List, Optional
import asyncio
from repi.llm.provider import LLMProvider, Message

logger = logging.getLogger(__name__)

class LLMError(Exception):
    def __init__(self, message: str, provider: str, model: str):
        super().__init__(f"{provider} ({model}) error: {message}")
        self.provider = provider
        self.model = model

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._api_key = api_key
        self._model = model
        self._url = "https://api.openai.com/v1/chat/completions"

    async def complete(self, messages: List[Message], max_tokens: int = 2000, temperature: float = 0.0) -> str:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "messages": [{"role": m.role, "content": m.content} for m in messages],
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    }
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise LLMError(str(e), "openai", self._model)

    @property
    def model_name(self) -> str:
        return self._model

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20240620"):
        self._api_key = api_key
        self._model = model
        self._url = "https://api.anthropic.com/v1/messages"

    async def complete(self, messages: List[Message], max_tokens: int = 2000, temperature: float = 0.0) -> str:
        try:
            system_msg = next((m.content for m in messages if m.role == "system"), None)
            user_messages = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._url,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": self._model,
                        "system": system_msg,
                        "messages": user_messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    }
                )
                response.raise_for_status()
                return response.json()["content"][0]["text"]
        except Exception as e:
            raise LLMError(str(e), "anthropic", self._model)

    @property
    def model_name(self) -> str:
        return self._model

class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "mistral"):
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def complete(self, messages: List[Message], max_tokens: int = 2000, temperature: float = 0.0) -> str:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [{"role": m.role, "content": m.content} for m in messages],
                        "stream": False,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": temperature
                        }
                    }
                )
                response.raise_for_status()
                return response.json()["message"]["content"]
        except Exception as e:
            raise LLMError(str(e), "ollama", self._model)

    @property
    def model_name(self) -> str:
        return self._model

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-pro"):
        self._api_key = api_key
        self._model = model
        # Base URL for Gemini API
        self._url_tmpl = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    async def complete(self, messages: List[Message], max_tokens: int = 2000, temperature: float = 0.0) -> str:
        try:
            contents = []
            for m in messages:
                # Gemini role mapping
                role = "user" if m.role in ["user", "system"] else "model"
                contents.append({"role": role, "parts": [{"text": m.content}]})
            
            url = self._url_tmpl.format(model=self._model, key=self._api_key)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url,
                    json={
                        "contents": contents,
                        "generationConfig": {
                            "maxOutputTokens": max_tokens,
                            "temperature": temperature
                        }
                    }
                )
                response.raise_for_status()
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            raise LLMError(str(e), "gemini", self._model)

    @property
    def model_name(self) -> str:
        return self._model

class MistralProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        self._api_key = api_key
        self._model = model
        self._url = "https://api.mistral.ai/v1/chat/completions"

    async def complete(self, messages: List[Message], max_tokens: int = 2000, temperature: float = 0.0) -> str:
        MAX_RETRIES = 3
        BASE_DELAY = 15.0  # seconds - Mistral free tier resets per minute
        
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        self._url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={
                            "model": self._model,
                            "messages": [{"role": m.role, "content": m.content} for m in messages],
                            "max_tokens": max_tokens,
                            "temperature": temperature
                        }
                    )
                    
                    if response.status_code == 429:
                        if attempt == MAX_RETRIES - 1:
                            raise LLMError(f"Rate limited after {MAX_RETRIES} retries", "mistral", self._model)
                        
                        import random
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = float(retry_after) + random.uniform(0, 2)
                                source = "Retry-After header"
                            except ValueError:
                                delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 5)
                                source = "exponential backoff (invalid header)"
                        else:
                            delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 5)
                            source = "exponential backoff"
                            
                        logger.warning(f"Mistral 429 — waiting {delay:.1f}s (source: {source}) before retry {attempt + 1}/{MAX_RETRIES}")
                        await asyncio.sleep(delay)
                        continue

                    response.raise_for_status()
                    return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                if isinstance(e, LLMError):
                    raise
                if attempt == MAX_RETRIES - 1:
                    raise LLMError(str(e), "mistral", self._model)
                logger.warning(f"Mistral attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(1.0)
        
    @property
    def model_name(self) -> str:
        return self._model
