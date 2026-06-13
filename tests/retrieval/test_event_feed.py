"""Rule-engine tests for the project-overview event feed (UX P2).

derive_events is a pure function over bucket aggregates — these tests pin
each rule (begins / spike / subsides / new_pattern / health) without a DB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repi.retrieval.event_feed import N_BUCKETS, derive_events, parse_window

TF = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
TT = TF + timedelta(hours=24)  # bucket span = 1h with N_BUCKETS=24


def _row(sig: str, bucket: int, n: int, service: str = "auth", level: str = "ERROR"):
    return {"service": service, "signature": sig, "level": level, "bucket": bucket, "n": n}


def _events(buckets, first_seen=None, **kw):
    return derive_events(buckets, first_seen or {}, TF, TT, **kw)


def _kinds(events, sig=None):
    return [e["kind"] for e in events if sig is None or e.get("signature") == sig]


# ── parse_window ─────────────────────────────────────────────────────────────

def test_parse_window_units():
    assert parse_window("5h") == timedelta(hours=5)
    assert parse_window("30m") == timedelta(minutes=30)
    assert parse_window("7d") == timedelta(days=7)


def test_parse_window_garbage_defaults_to_5h():
    assert parse_window("soon") == timedelta(hours=5)
    assert parse_window("-3h") == timedelta(hours=5)


# ── begins ───────────────────────────────────────────────────────────────────

def test_begins_emitted_for_quiet_then_burst():
    events = _events([_row("jwt failed", bucket=5, n=10)])
    assert "begins" in _kinds(events, "jwt failed")


def test_no_begins_when_active_at_window_edge():
    """Already firing in bucket 1 — we didn't observe it begin."""
    events = _events([_row("jwt failed", bucket=1, n=10)])
    assert "begins" not in _kinds(events, "jwt failed")


def test_no_begins_below_threshold():
    events = _events([_row("jwt failed", bucket=5, n=2)])
    assert "begins" not in _kinds(events, "jwt failed")


def test_info_levels_never_produce_events():
    events = _events([_row("served request", bucket=5, n=500, level="INFO")])
    assert _kinds(events, "served request") == []


# ── spike ────────────────────────────────────────────────────────────────────

def test_spike_on_3x_trailing_average():
    buckets = [
        _row("db timeout", 2, 4),
        _row("db timeout", 3, 4),
        _row("db timeout", 10, 40),  # 10x the trailing average
    ]
    events = _events(buckets)
    kinds = _kinds(events, "db timeout")
    assert "spike" in kinds
    spike = next(e for e in events if e["kind"] == "spike")
    assert spike["count"] == 40
    assert "×40" in spike["title"]


def test_no_spike_for_flat_series():
    buckets = [_row("db timeout", b, 10) for b in range(2, 12)]
    assert "spike" not in _kinds(_events(buckets), "db timeout")


# ── subsides ─────────────────────────────────────────────────────────────────

def test_subsides_when_activity_stops_before_window_end():
    buckets = [_row("redis down", 4, 10), _row("redis down", 5, 8)]
    events = _events(buckets)
    assert "subsides" in _kinds(events, "redis down")


def test_no_subsides_when_still_active_at_end():
    buckets = [_row("redis down", N_BUCKETS - 1, 10), _row("redis down", N_BUCKETS, 8)]
    assert "subsides" not in _kinds(_events(buckets), "redis down")


# ── new_pattern ──────────────────────────────────────────────────────────────

def test_new_pattern_replaces_begins():
    first_seen = {"jwt sig mismatch": TF + timedelta(hours=4)}
    events = _events([_row("jwt sig mismatch", 5, 10)], first_seen)
    kinds = _kinds(events, "jwt sig mismatch")
    assert "new_pattern" in kinds
    assert "begins" not in kinds


def test_old_pattern_is_not_new():
    first_seen = {"jwt failed": TF - timedelta(days=30)}
    events = _events([_row("jwt failed", 5, 10)], first_seen)
    assert "new_pattern" not in _kinds(events, "jwt failed")


# ── health transitions ───────────────────────────────────────────────────────

def test_service_degraded_and_recovers():
    buckets = [
        # bucket 3: 20 rows, 15 errors → degraded (75%)
        _row("boom", 3, 15, service="pay", level="ERROR"),
        _row("ok", 3, 5, service="pay", level="INFO"),
        # bucket 8: 20 rows, 2 errors → recovered (10%)
        _row("boom", 8, 2, service="pay", level="ERROR"),
        _row("ok", 8, 18, service="pay", level="INFO"),
    ]
    events = _events(buckets)
    kinds = [e["kind"] for e in events if e["service"] == "pay"]
    assert "health_degraded" in kinds
    assert "health_recovered" in kinds
    # Degraded must precede recovered chronologically.
    assert kinds.index("health_degraded") < kinds.index("health_recovered")


def test_no_health_event_below_volume_floor():
    buckets = [
        _row("boom", 3, 4, service="pay", level="ERROR"),
        _row("ok", 3, 1, service="pay", level="INFO"),
    ]
    events = _events(buckets)
    assert all(e["kind"] != "health_degraded" for e in events)


# ── cap + ordering ───────────────────────────────────────────────────────────

def test_events_capped_and_chronological():
    buckets = []
    for i in range(40):
        buckets.append(_row(f"sig-{i}", bucket=3 + (i % 10), n=10, service=f"svc{i}"))
    events = _events(buckets, max_events=10)
    assert len(events) == 10
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)
