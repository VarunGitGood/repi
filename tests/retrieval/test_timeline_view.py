"""Pure-function tests for the chat-path timeline view.

Contract:
  - Sort retrieved chunks by timestamp.
  - Collapse runs of adjacent (service, level, signature) into one entry
    with first_ts/last_ts and repeat_count.
  - Drop chunks without timestamps; a timeline can't place them.
  - Different log levels for the same signature stay as separate entries.
"""
from __future__ import annotations

from repi.retrieval.timeline_view import build_timeline


def _chunk(text: str, service: str, level: str, timestamp: str | None):
    return {
        "chunk_id": f"c-{service}-{timestamp}",
        "service": service,
        "level": level,
        "timestamp": timestamp,
        "text": text,
    }


def test_returns_empty_for_no_chunks():
    assert build_timeline([]) == []


def test_returns_empty_when_all_chunks_lack_timestamp():
    chunks = [_chunk("Signature: x\nExamples: y", "svc", "ERROR", None)]
    assert build_timeline(chunks) == []


def test_single_chunk_produces_one_entry():
    chunks = [_chunk("Signature: jwt failed\nExamples: a", "auth", "ERROR", "2026-06-09T14:02:00")]
    out = build_timeline(chunks)
    assert len(out) == 1
    assert out[0]["repeat_count"] == 1
    assert out[0]["first_ts"] == out[0]["last_ts"] == "2026-06-09T14:02:00"
    assert out[0]["signature"] == "jwt failed"


def test_consecutive_run_collapses_with_range_and_count():
    """The whole point of the run-collapse — 'x12 over 14:02–14:04'."""
    chunks = [
        _chunk("Signature: jwt failed\nExamples: a", "auth", "ERROR", "2026-06-09T14:02:00"),
        _chunk("Signature: jwt failed\nExamples: b", "auth", "ERROR", "2026-06-09T14:03:00"),
        _chunk("Signature: jwt failed\nExamples: c", "auth", "ERROR", "2026-06-09T14:04:00"),
    ]
    out = build_timeline(chunks)
    assert len(out) == 1
    assert out[0]["repeat_count"] == 3
    assert out[0]["first_ts"] == "2026-06-09T14:02:00"
    assert out[0]["last_ts"] == "2026-06-09T14:04:00"


def test_different_services_dont_collapse_even_with_same_signature():
    """Cross-service signature match is a coincidence, not a run.
    Two services emitting "auth check failed" is two events, not one."""
    chunks = [
        _chunk("Signature: auth check failed\nExamples: x", "auth-service", "ERROR", "2026-06-09T14:02:00"),
        _chunk("Signature: auth check failed\nExamples: y", "api-gateway", "ERROR", "2026-06-09T14:03:00"),
    ]
    out = build_timeline(chunks)
    assert [e["service"] for e in out] == ["auth-service", "api-gateway"]


def test_different_levels_dont_collapse_even_with_same_signature():
    """An ERROR and a WARNING with the same masked template are two
    different observations — INFO setup ≠ ERROR fallout."""
    chunks = [
        _chunk("Signature: token validation\nExamples: a", "auth", "INFO", "2026-06-09T14:02:00"),
        _chunk("Signature: token validation\nExamples: b", "auth", "ERROR", "2026-06-09T14:03:00"),
    ]
    out = build_timeline(chunks)
    assert len(out) == 2
    assert out[0]["level"] == "INFO"
    assert out[1]["level"] == "ERROR"


def test_runs_break_then_resume_produce_separate_entries():
    """A B A → three entries. The two A's are not consecutive."""
    chunks = [
        _chunk("Signature: A\nExamples: 1", "svc-a", "ERROR", "2026-06-09T14:00:00"),
        _chunk("Signature: A\nExamples: 2", "svc-a", "ERROR", "2026-06-09T14:01:00"),
        _chunk("Signature: B\nExamples: 1", "svc-a", "ERROR", "2026-06-09T14:02:00"),
        _chunk("Signature: A\nExamples: 3", "svc-a", "ERROR", "2026-06-09T14:03:00"),
    ]
    out = build_timeline(chunks)
    sigs = [(e["signature"], e["repeat_count"]) for e in out]
    assert sigs == [("A", 2), ("B", 1), ("A", 1)]


def test_unsorted_input_is_sorted_chronologically():
    """The chat path's chunks are RRF-ranked, not time-sorted. The timeline
    must impose chronological order."""
    chunks = [
        _chunk("Signature: B\nExamples: y", "svc", "ERROR", "2026-06-09T14:03:00"),
        _chunk("Signature: A\nExamples: x", "svc", "ERROR", "2026-06-09T14:01:00"),
        _chunk("Signature: C\nExamples: z", "svc", "ERROR", "2026-06-09T14:05:00"),
    ]
    out = build_timeline(chunks)
    assert [e["signature"] for e in out] == ["A", "B", "C"]


def test_chunks_without_timestamps_are_dropped():
    """Mixed input — only the timestamped ones land in the timeline."""
    chunks = [
        _chunk("Signature: orphan\nExamples: x", "svc", "ERROR", None),
        _chunk("Signature: anchored\nExamples: y", "svc", "ERROR", "2026-06-09T14:00:00"),
    ]
    out = build_timeline(chunks)
    assert len(out) == 1
    assert out[0]["signature"] == "anchored"


def test_chunks_without_signature_are_dropped():
    """Defensive: empty text → no signature → can't form a run key."""
    chunks = [
        {"text": "", "service": "svc", "level": "ERROR", "timestamp": "2026-06-09T14:00:00"},
        _chunk("Signature: real\nExamples: y", "svc", "ERROR", "2026-06-09T14:01:00"),
    ]
    out = build_timeline(chunks)
    assert len(out) == 1
    assert out[0]["signature"] == "real"
