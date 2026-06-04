"""Tests for adapter error classification (Issue #48 Priority 7).

- 429 surfaces as LLMRateLimitError (caller can wait, doesn't get a retry-burn budget)
- 4xx (non-429) surfaces as LLMBadRequestError (caller must NOT retry)
- Mistral adapter does not count 429 waits toward its transient-retry budget
"""
from __future__ import annotations

import httpx
import pytest

from repi.llm.adapters import (
    _check_4xx,
    LLMRateLimitError,
    LLMBadRequestError,
    LLMError,
    MistralProvider,
)
from repi.llm.provider import Message


def _resp(status: int, body: str = "", headers: dict | None = None) -> httpx.Response:
    req = httpx.Request("POST", "https://example.test")
    return httpx.Response(status, content=body.encode(), headers=headers or {}, request=req)


class TestCheck4xx:
    def test_429_raises_rate_limit_error_with_retry_after(self):
        r = _resp(429, '{"err":"slow down"}', headers={"Retry-After": "12"})
        with pytest.raises(LLMRateLimitError) as exc:
            _check_4xx(r, "test", "model-x")
        assert exc.value.retry_after == 12.0

    def test_429_without_retry_after_still_raises(self):
        r = _resp(429, "")
        with pytest.raises(LLMRateLimitError):
            _check_4xx(r, "test", "model-x")

    def test_400_raises_bad_request(self):
        r = _resp(400, '{"err": "bad payload"}')
        with pytest.raises(LLMBadRequestError) as exc:
            _check_4xx(r, "test", "model-x")
        assert exc.value.status_code == 400
        assert "bad payload" in exc.value.body

    def test_401_raises_bad_request(self):
        with pytest.raises(LLMBadRequestError):
            _check_4xx(_resp(401, "unauthorized"), "test", "model-x")

    def test_403_raises_bad_request(self):
        with pytest.raises(LLMBadRequestError):
            _check_4xx(_resp(403, "forbidden"), "test", "model-x")

    def test_5xx_does_not_raise(self):
        # 5xx is server-side; httpx.raise_for_status handles it. _check_4xx
        # is only responsible for the 4xx branch.
        _check_4xx(_resp(500, "boom"), "test", "model-x")
        _check_4xx(_resp(503, "down"), "test", "model-x")

    def test_2xx_does_not_raise(self):
        _check_4xx(_resp(200, "ok"), "test", "model-x")
        _check_4xx(_resp(204, ""), "test", "model-x")

    def test_error_inheritance(self):
        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMBadRequestError, LLMError)


# ─── Mistral adapter behavior ────────────────────────────────────────────────


class TestMistralAdapter:
    @pytest.mark.asyncio
    async def test_mistral_400_raises_bad_request_no_retry(self, monkeypatch):
        """A 400 from Mistral must raise LLMBadRequestError on the FIRST attempt
        — the adapter must not retry the request."""
        call_count = {"n": 0}

        class _MockResponse:
            status_code = 400
            headers: dict = {}
            text = '{"error": {"message": "bad request"}}'
            def json(self): return {"error": {"message": "bad request"}}
            def raise_for_status(self): raise httpx.HTTPStatusError("400", request=None, response=None)

        class _MockClient:
            def __init__(self, **_kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def post(self, *args, **kwargs):
                call_count["n"] += 1
                return _MockResponse()

        monkeypatch.setattr("repi.llm.adapters.httpx.AsyncClient", _MockClient)

        provider = MistralProvider(api_key="test", model="mistral-large-latest")
        with pytest.raises(LLMBadRequestError) as exc:
            await provider.complete([Message(role="user", content="hi")])

        assert exc.value.status_code == 400
        # NO retry: only one POST was issued.
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_mistral_429_waits_without_counting_toward_transient_budget(self, monkeypatch):
        """Multiple 429s should keep waiting until the rate-limit cap; transient
        retry budget (3) must NOT be exhausted by them."""
        call_count = {"n": 0}
        sleep_count = {"n": 0}

        class _MockResponse429:
            status_code = 429
            headers = {"Retry-After": "0"}
            text = ""
            def json(self): return {}
            def raise_for_status(self): pass

        class _MockResponse200:
            status_code = 200
            headers: dict = {}
            text = ""
            def json(self): return {"choices": [{"message": {"content": "ok"}}]}
            def raise_for_status(self): pass

        class _MockClient:
            def __init__(self, **_kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def post(self, *_args, **_kwargs):
                call_count["n"] += 1
                # First 5 calls are 429, then a 200 success.
                if call_count["n"] <= 5:
                    return _MockResponse429()
                return _MockResponse200()

        async def _no_sleep(_):
            sleep_count["n"] += 1

        monkeypatch.setattr("repi.llm.adapters.httpx.AsyncClient", _MockClient)
        monkeypatch.setattr("repi.llm.adapters.asyncio.sleep", _no_sleep)

        provider = MistralProvider(api_key="test", model="mistral-large-latest")
        result = await provider.complete([Message(role="user", content="hi")])

        # Adapter waited through 5 rate-limits and succeeded on the 6th call.
        assert result == "ok"
        assert call_count["n"] == 6
        # 5 rate-limit sleeps fired (one per 429).
        assert sleep_count["n"] == 5
