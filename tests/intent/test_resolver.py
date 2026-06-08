from datetime import datetime, timedelta

import pytest

from repi.intent.resolver import (
    ClarificationNeeded,
    ResolvedIntent,
    _extract_entities,
    resolve,
)


# A fixed "now" — Wednesday 2026-06-10 12:00:00 UTC. Tests pick weekdays that
# don't collide with this so the ambiguous-weekday branch isn't triggered.
NOW = datetime(2026, 6, 10, 12, 0, 0)


# ── Gate behaviour ────────────────────────────────────────────────────────────

def test_entity_only_no_clarification():
    """A bare entity ID with no time and no service must NOT clarify."""
    res = resolve("why did blk_-160 fail", known_services=[], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert res.entities == ["blk_-160"]
    assert res.time_from is None
    assert res.time_to is None
    assert res.services == []


def test_service_only_no_clarification():
    """A known service with no time must NOT clarify and must NOT default to 1h."""
    res = resolve("errors in cart-svc", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert res.services == ["cart-svc"]
    assert res.time_from is None
    assert res.time_to is None


def test_time_only_no_clarification():
    res = resolve("last 2 hours", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert res.time_from is not None
    assert res.time_to is not None
    assert res.services == []
    assert res.entities == []


def test_all_three_missing_clarifies():
    """No id, no service, no time → single unified clarification."""
    res = resolve("why did things break", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ClarificationNeeded)
    assert res.missing_dims == ["id_or_service_or_time"]
    assert "ID" in res.question and "service" in res.question and "time" in res.question


def test_symptom_alone_does_not_satisfy_gate():
    """Per A3 spec: symptoms (errors/timeouts) do NOT count as a dimension."""
    res = resolve("seeing 500 errors", known_services=["cart-svc"], now=NOW)
    assert isinstance(res, ClarificationNeeded)


def test_no_default_to_last_hour():
    """The old 'default to last 1 hour' fallback is gone."""
    res = resolve("blk_42", known_services=[], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert res.time_from is None
    assert res.time_to is None
    assert not any("defaulting" in a for a in res.assumed)


def test_ambiguous_weekday_rescued_by_entity():
    """User says weekday matching today without 'last/this' — time stays None,
    but the entity rescues the gate so we proceed without clarification."""
    # NOW is Wednesday — "wednesday" alone is ambiguous which week.
    res = resolve("blk_42 failed wednesday", known_services=[], now=NOW)
    assert isinstance(res, ResolvedIntent)
    assert "blk_42" in res.entities
    assert res.time_from is None


# ── Entity extraction ─────────────────────────────────────────────────────────

def test_extract_hdfs_block_id():
    assert _extract_entities("why did blk_-1608999687919862906 fail", []) == [
        "blk_-1608999687919862906"
    ]


def test_extract_request_id():
    assert _extract_entities("show me req_abc-123", []) == ["req_abc-123"]


def test_extract_uuid():
    out = _extract_entities("trace 550e8400-e29b-41d4-a716-446655440000", [])
    assert out == ["550e8400-e29b-41d4-a716-446655440000"]


def test_extract_hex_hash():
    out = _extract_entities("commit abc123def4567", [])
    assert out == ["abc123def4567"]


def test_known_service_not_extracted_as_entity():
    """`cart-svc` matches the hyphenated-identifier pattern but is a known
    service — it must not double-count as an entity."""
    out = _extract_entities("errors in cart-svc", ["cart-svc"])
    assert out == []


def test_entity_dedup():
    out = _extract_entities("blk_42 saw blk_42 again", [])
    assert out == ["blk_42"]


def test_entity_case_insensitive_dedup():
    out = _extract_entities("BLK_42 and blk_42", [])
    assert len(out) == 1
