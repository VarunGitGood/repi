"""Unit tests for find_logs_by_id and the A4 confidence floors.

The tool itself is a thin SQL wrapper — we verify it builds the right query,
returns the standard chunk-dict shape, and handles the empty-entity edge case.
The confidence-floor tests live here too because they are the runtime contract
A4 ships together with the tool.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from repi.investigation.schema import enforce_floors
from repi.investigation.tools import find_logs_by_id


# ── find_logs_by_id ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_logs_by_id_empty_entity_returns_empty():
    """No DB call should happen for an empty/whitespace entity."""
    pool = MagicMock()
    pool.fetch = AsyncMock()
    assert await find_logs_by_id(pool, entity="") == []
    assert await find_logs_by_id(pool, entity="   ") == []
    pool.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_find_logs_by_id_builds_ilike_query_and_returns_chunk_shape():
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[
        {
            "chunk_id": "chunk-1",
            "source_service": "hdfs",
            "log_level": "ERROR",
            "timestamp_start": datetime(2026, 6, 5, 12, 0, 0),
            "text": "block blk_-1608999687919862906 missing replica",
        },
    ])
    out = await find_logs_by_id(pool, entity="blk_-1608999687919862906", top_k=10)

    # Query shape
    args, _ = pool.fetch.call_args
    sql = args[0]
    assert "text ILIKE '%' || $1 || '%'" in sql
    assert "ORDER BY timestamp_start DESC" in sql
    assert args[1] == "blk_-1608999687919862906"
    assert args[2] == 10

    # Result shape
    assert out == [{
        "chunk_id": "chunk-1",
        "service": "hdfs",
        "level": "ERROR",
        "timestamp_start": "2026-06-05T12:00:00",
        "text": "block blk_-1608999687919862906 missing replica",
    }]


@pytest.mark.asyncio
async def test_find_logs_by_id_strips_entity():
    """Leading/trailing whitespace is stripped before the SQL parameter is bound."""
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[])
    await find_logs_by_id(pool, entity="  req_abc  ")
    args, _ = pool.fetch.call_args
    assert args[1] == "req_abc"


# ── Confidence floors (A4 soft-fail contract) ─────────────────────────────────

def _answer(confidence: str, cited: int = 0, gaps: list[str] | None = None) -> dict:
    """Helper: build a minimal-ish answer dict the way enforce_floors expects."""
    trigger = {"chunk_id": "c1"} if cited >= 1 else {}
    chain = [{"chunk_id": f"c{i+2}"} for i in range(max(cited - 1, 0))]
    return {
        "confidence": confidence,
        "trigger_event": trigger,
        "propagation_chain": chain,
        "affected_services": [],
        "gaps": list(gaps) if gaps else [],
    }


def test_empty_evidence_forces_low():
    ans = _answer(confidence="high", cited=2)
    adjusted, notes = enforce_floors(ans, evidence=[])
    assert adjusted["confidence"] == "low"
    assert any("no evidence chunks" in n for n in notes)


def test_entity_absent_from_evidence_forces_low():
    """The user anchored on an ID but no chunk contains it — distrust the answer."""
    ev = [{"chunk_id": "c1", "service": "svc", "text": "unrelated log line"}]
    ans = _answer(confidence="high", cited=2, gaps=["x"])
    adjusted, notes = enforce_floors(
        ans, evidence=ev, resolved_entities=["blk_-160"],
    )
    assert adjusted["confidence"] == "low"
    assert any("query anchor" in n for n in notes)


def test_entity_present_in_one_chunk_does_not_force_low():
    """If *any* chunk literally contains *any* resolved entity, the A4 floor stays off."""
    ev = [
        {"chunk_id": "c1", "service": "svc", "text": "saw blk_-160 in pipeline"},
        {"chunk_id": "c2", "service": "svc", "text": "unrelated"},
    ]
    ans = _answer(confidence="high", cited=2, gaps=["x"])
    adjusted, notes = enforce_floors(
        ans, evidence=ev, resolved_entities=["blk_-160"],
    )
    # Not forced low by A4 entity-presence rule.
    assert not any("query anchor" in n for n in notes)


def test_resolved_entities_none_skips_check():
    """Backwards-compat: callers that don't pass entities behave exactly as before."""
    ev = [{"chunk_id": "c1", "service": "svc", "text": "anything", "level": "ERROR"}]
    ans = _answer(confidence="high", cited=2, gaps=["x"])
    adjusted, _ = enforce_floors(ans, evidence=ev)  # no resolved_entities kwarg
    assert adjusted["confidence"] in {"high", "medium"}  # whatever pre-A4 logic said
