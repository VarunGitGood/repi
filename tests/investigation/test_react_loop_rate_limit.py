from __future__ import annotations

import pytest

from repi.investigation.react_loop import ReactInvestigationLoop


class _DummyLLM:
    async def complete(self, messages, max_tokens=1000, temperature=0.0):
        return "{}"

    @property
    def model_name(self) -> str:
        return "dummy"


@pytest.mark.asyncio
async def test_wait_for_rate_limit_waits_when_limit_reached(monkeypatch):
    loop = ReactInvestigationLoop(
        llm=_DummyLLM(),
        tools={},
        known_services=[],
        llm_max_calls_per_min=2,
    )
    loop._llm_call_timestamps = [100.0, 110.0]

    now_values = iter([120.0, 181.5, 181.5, 181.5, 181.5])
    monkeypatch.setattr("repi.investigation.react_loop.time.time", lambda: next(now_values))

    sleeps = []

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)

    monkeypatch.setattr("repi.investigation.react_loop.asyncio.sleep", fake_sleep)

    await loop._wait_for_rate_limit()

    assert sleeps == [41.0]
    assert loop._llm_call_timestamps == [181.5]


@pytest.mark.asyncio
async def test_wait_for_rate_limit_does_not_wait_when_under_limit(monkeypatch):
    loop = ReactInvestigationLoop(
        llm=_DummyLLM(),
        tools={},
        known_services=[],
        llm_max_calls_per_min=60,
    )
    loop._llm_call_timestamps = [100.0, 110.0, 120.0]
    monkeypatch.setattr("repi.investigation.react_loop.time.time", lambda: 150.0)

    sleeps = []

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)

    monkeypatch.setattr("repi.investigation.react_loop.asyncio.sleep", fake_sleep)

    await loop._wait_for_rate_limit()

    assert sleeps == []
    assert loop._llm_call_timestamps[-1] == 150.0
