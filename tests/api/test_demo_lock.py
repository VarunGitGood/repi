"""Read-only demo lock (Settings.DEMO_MODE): mutating + non-showcase endpoints
are guarded, token-burning endpoints share a daily budget, and the showcase
flow (investigate/clarify/chat + the reads it needs) stays open."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from repi.api import app
from repi.api import guards
from repi.api.guards import block_in_demo, llm_daily_budget
from repi.api.limiter import limiter
from repi.core.config import settings


# ── helpers ──────────────────────────────────────────────────────────────────

def _guards_on(path: str, method: str) -> set[str]:
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == path and method in r.methods:
            names: set[str] = set()

            def walk(dep):
                for sub in dep.dependencies:
                    walk(sub)
                if dep.call is not None:
                    names.add(getattr(dep.call, "__name__", str(dep.call)))

            walk(r.dependant)
            return names
    raise AssertionError(f"route {method} {path} not found")


@pytest.fixture
def reset_budget():
    guards._budget["date"] = None
    guards._budget["count"] = 0
    yield


# ── guard function behaviour ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_block_in_demo_noop_when_off(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    await block_in_demo()  # no raise


@pytest.mark.asyncio
async def test_block_in_demo_403_when_on(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    with pytest.raises(HTTPException) as ei:
        await block_in_demo()
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_daily_budget_ignored_outside_demo(monkeypatch, reset_budget):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "DEMO_DAILY_LLM_BUDGET", 1)
    for _ in range(5):
        await llm_daily_budget()  # never raises when demo off


@pytest.mark.asyncio
async def test_daily_budget_caps_in_demo(monkeypatch, reset_budget):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    monkeypatch.setattr(settings, "DEMO_DAILY_LLM_BUDGET", 3)
    for _ in range(3):
        await llm_daily_budget()  # first 3 pass
    with pytest.raises(HTTPException) as ei:
        await llm_daily_budget()  # 4th over budget
    assert ei.value.status_code == 429


# ── wiring: the right endpoints carry the right guards ───────────────────────

@pytest.mark.parametrize("method,path", [
    ("POST", "/ingest"),
    ("POST", "/watchers"),
    ("GET", "/watchers"),
    ("GET", "/config"),
    ("PUT", "/config"),
    ("GET", "/leaderboard/summary"),
    ("POST", "/projects"),
])
def test_mutating_and_admin_routes_locked(method, path):
    assert "block_in_demo" in _guards_on(path, method)


@pytest.mark.parametrize("path", [
    "/investigate",
    "/investigations/{investigation_id}/clarify",
    "/chat",
])
def test_token_routes_share_daily_budget(path):
    assert "llm_daily_budget" in _guards_on(path, "POST")


@pytest.mark.parametrize("method,path", [
    ("GET", "/services"),
    ("GET", "/conversations"),
    ("GET", "/projects"),
    ("GET", "/investigations"),
])
def test_showcase_reads_stay_open(method, path):
    g = _guards_on(path, method)
    assert "block_in_demo" not in g


# ── rate limits ──────────────────────────────────────────────────────────────

def test_rate_limits_are_stingy():
    limits = {fn: [str(x.limit) for x in v]
              for fn, v in limiter._route_limits.items()}
    assert limits["repi.api.investigate.investigate"] == ["3 per 1 minute"]
    assert limits["repi.api.investigate.clarify_investigation"] == ["3 per 1 minute"]
    assert limits["repi.api.chat.chat"] == ["5 per 1 minute"]
