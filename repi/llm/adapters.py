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


class LLMRateLimitError(LLMError):
    """Raised when the provider returns 429. Do not retry-blast — wait."""

    def __init__(self, provider: str, model: str, retry_after: float | None = None):
        super().__init__(
            f"rate limited" + (f" (retry after {retry_after}s)" if retry_after else ""),
            provider, model,
        )
        self.retry_after = retry_after


class LLMBadRequestError(LLMError):
    """Raised for 4xx (non-429) — bad payload, bad auth, etc. NEVER retry."""

    def __init__(self, provider: str, model: str, status_code: int, body: str):
        super().__init__(f"HTTP {status_code}: {body[:300]}", provider, model)
        self.status_code = status_code
        self.body = body


async def _post_with_429_retry(url: str, *, provider: str, model: str,
                               headers: Optional[dict] = None, json_body: dict,
                               max_rate_limit_waits: int = 5,
                               base_delay: float = 15.0) -> httpx.Response:
    """POST, waiting out 429s instead of failing: honor Retry-After when the
    provider sends it, exponential backoff with jitter otherwise. Raises
    LLMRateLimitError once max_rate_limit_waits is exhausted. Non-429
    responses are returned as-is for the caller to classify."""
    import random
    waits = 0
    while True:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=json_body)

        if response.status_code != 429:
            return response

        waits += 1
        if waits > max_rate_limit_waits:
            raise LLMRateLimitError(provider, model)

        delay = None
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = float(retry_after) + random.uniform(0, 2)
                source = "Retry-After header"
            except ValueError:
                delay = None
        if delay is None:
            delay = base_delay * (2 ** min(waits, 3)) + random.uniform(0, 5)
            source = "exponential backoff"

        logger.warning(
            "%s 429 — waiting %.1fs (source: %s) — wait #%d/%d",
            provider, delay, source, waits, max_rate_limit_waits,
        )
        await asyncio.sleep(delay)


def _check_4xx(response: httpx.Response, provider: str, model: str) -> None:
    """Raise typed errors for 4xx responses. 429 surfaces as a retryable
    rate-limit error; other 4xx as bad-request (do not retry)."""
    if response.status_code == 429:
        retry_after = None
        ra = response.headers.get("Retry-After")
        if ra:
            try:
                retry_after = float(ra)
            except ValueError:
                pass
        raise LLMRateLimitError(provider, model, retry_after=retry_after)
    if 400 <= response.status_code < 500:
        body = ""
        try:
            body = response.text
        except Exception:
            pass
        logger.warning("%s %d body: %s", provider, response.status_code, body[:500])
        raise LLMBadRequestError(provider, model, response.status_code, body)

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._api_key = api_key
        self._model = model
        self._url = "https://api.openai.com/v1/chat/completions"

    async def complete(self, messages: List[Message], max_tokens: int = 2000, temperature: float = 0.0) -> str:
        try:
            response = await _post_with_429_retry(
                self._url, provider="openai", model=self._model,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json_body={
                    "model": self._model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }
            )
            _check_4xx(response, "openai", self._model)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except LLMError:
            raise
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

            response = await _post_with_429_retry(
                self._url, provider="anthropic", model=self._model,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json_body={
                    "model": self._model,
                    "system": system_msg,
                    "messages": user_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }
            )
            _check_4xx(response, "anthropic", self._model)
            response.raise_for_status()
            return response.json()["content"][0]["text"]
        except LLMError:
            raise
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
                _check_4xx(response, "ollama", self._model)
                response.raise_for_status()
                return response.json()["message"]["content"]
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(str(e), "ollama", self._model)

    @property
    def model_name(self) -> str:
        return self._model

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-pro"):
        self._api_key = api_key
        self._model = model
        self._url_tmpl = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    async def complete(self, messages: List[Message], max_tokens: int = 2000, temperature: float = 0.0) -> str:
        try:
            contents = []
            for m in messages:
                role = "user" if m.role in ["user", "system"] else "model"
                contents.append({"role": role, "parts": [{"text": m.content}]})
            
            url = self._url_tmpl.format(model=self._model, key=self._api_key)
            response = await _post_with_429_retry(
                url, provider="gemini", model=self._model,
                json_body={
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "temperature": temperature
                    }
                }
            )
            _check_4xx(response, "gemini", self._model)
            response.raise_for_status()
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except LLMError:
            raise
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
        MAX_TRANSIENT_RETRIES = 3   # network blips, timeouts, 5xx
        MAX_RATE_LIMIT_WAITS = 10   # 429s — these don't count as failures, they're "wait and try again"

        transient_attempts = 0

        while True:
            try:
                response = await _post_with_429_retry(
                    self._url, provider="mistral", model=self._model,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json_body={
                        "model": self._model,
                        "messages": [{"role": m.role, "content": m.content} for m in messages],
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    },
                    max_rate_limit_waits=MAX_RATE_LIMIT_WAITS,
                )
                # 4xx (non-429): typed bad-request, no retry.
                _check_4xx(response, "mistral", self._model)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            except LLMRateLimitError:
                raise
            except LLMBadRequestError:
                raise
            except Exception as e:
                transient_attempts += 1
                if transient_attempts >= MAX_TRANSIENT_RETRIES:
                    raise LLMError(str(e), "mistral", self._model)
                logger.warning(
                    "Mistral transient error (attempt %d/%d): %s",
                    transient_attempts, MAX_TRANSIENT_RETRIES, e,
                )
                await asyncio.sleep(1.0)
        
    @property
    def model_name(self) -> str:
        return self._model
