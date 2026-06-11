"""Verify the /chat `done` event carries a `timeline` payload.

build_timeline itself is exercised in tests/retrieval/test_timeline_view.py.
Here we pin the wire-contract shape the UI's Timeline.tsx binds to.
"""
from __future__ import annotations

from repi.retrieval.timeline_view import build_timeline


def _chunk(sig: str, service: str, level: str, ts: str):
    return {
        "chunk_id": f"id-{sig}-{ts}",
        "service": service,
        "level": level,
        "timestamp": ts,
        "text": f"Signature: {sig}\nExamples: x",
    }


def test_chat_done_timeline_payload_shape():
    """Exact keys the web/components/chat/Timeline.tsx component reads."""
    chunks = [
        _chunk("jwt failed", "auth-service", "ERROR", "2026-06-09T14:02:00"),
        _chunk("jwt failed", "auth-service", "ERROR", "2026-06-09T14:03:00"),
        _chunk("db timeout", "payments", "ERROR", "2026-06-09T14:05:00"),
    ]

    timeline = build_timeline(chunks)

    assert len(timeline) == 2
    assert set(timeline[0].keys()) == {
        "service", "level", "signature",
        "first_ts", "last_ts", "repeat_count",
    }
    assert timeline[0]["service"] == "auth-service"
    assert timeline[0]["repeat_count"] == 2
    assert timeline[1]["service"] == "payments"
    assert timeline[1]["repeat_count"] == 1


def test_chat_done_timeline_empty_when_no_timestamps():
    chunks = [
        {"text": "Signature: x\nExamples: y", "service": "svc", "level": "ERROR", "timestamp": None}
    ]
    assert build_timeline(chunks) == []
