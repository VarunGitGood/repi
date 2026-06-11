"""Projects (UX P1): resolver branches + settings merge + filter clause.

DB-backed CRUD is exercised in the live walkthrough; here we pin the pure
logic: name-or-id resolution, settings defaulting, and the retrieval filter.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from repi.api.projects import (
    DEFAULT_PROJECT_NAME,
    DEFAULT_SETTINGS,
    effective_settings,
    resolve_project,
)
from repi.models.filters import RetrievalFilters
from repi.models.schema import Project
from repi.retrieval.filter_builder import build_filter_expressions


# ── effective_settings ────────────────────────────────────────────────────────

def test_effective_settings_defaults_when_empty():
    p = Project(name="x", settings={})
    assert effective_settings(p) == DEFAULT_SETTINGS


def test_effective_settings_overrides_win():
    p = Project(name="x", settings={"default_timeline_window": "24h"})
    s = effective_settings(p)
    assert s["default_timeline_window"] == "24h"
    assert s["max_events"] == DEFAULT_SETTINGS["max_events"]


# ── resolve_project ───────────────────────────────────────────────────────────

def _session_returning(row):
    session = MagicMock()
    res = MagicMock()
    res.first.return_value = row
    session.exec = AsyncMock(return_value=res)
    session.get = AsyncMock(return_value=row)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_resolve_blank_falls_back_to_default_name():
    existing = Project(name=DEFAULT_PROJECT_NAME)
    session = _session_returning(existing)
    assert (await resolve_project(session, None)) is existing
    assert (await resolve_project(session, "  ")) is existing


@pytest.mark.asyncio
async def test_resolve_name_creates_when_missing():
    session = _session_returning(None)
    created = await resolve_project(session, "payments")
    session.add.assert_called_once()
    assert created.name == "payments"


@pytest.mark.asyncio
async def test_resolve_uuid_must_exist():
    session = _session_returning(None)
    with pytest.raises(HTTPException) as exc:
        await resolve_project(session, str(uuid4()))
    assert exc.value.status_code == 404
    # A typo'd id must NOT silently create a project named like a UUID.
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_uuid_returns_existing():
    pid = uuid4()
    existing = Project(id=pid, name="infra")
    session = _session_returning(existing)
    assert (await resolve_project(session, str(pid))) is existing


# ── retrieval filter clause ───────────────────────────────────────────────────

def test_filter_builder_no_project_no_clause():
    exprs = build_filter_expressions(RetrievalFilters())
    assert all("project_id" not in str(e) for e in exprs)


def test_filter_builder_project_clause_present():
    pid = uuid4()
    exprs = build_filter_expressions(RetrievalFilters(project_id=pid))
    assert any("project_id" in str(e) for e in exprs)
