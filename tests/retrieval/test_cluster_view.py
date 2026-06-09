"""Pure-function tests for runtime event clustering over a retrieved chunk set.

The contract:
  - Group by signature extracted from the templated `text` field.
  - Aggregate count, service set, and time range per signature.
  - Drop singletons (default min_count=2) so the panel surfaces real incidents.
  - Sort by count desc — the dominant event leads.
"""
from __future__ import annotations

from repi.retrieval.cluster_view import (
    ClusterView,
    cluster_chunks,
    _extract_signature,
)


def _chunk(text: str, service: str, timestamp: str):
    return {"text": text, "service": service, "timestamp": timestamp}


def test_extract_signature_from_templated_text():
    """Ingest path stores `"Signature: ...\\nExamples: ..."` — pull the
    signature back out for clustering."""
    body = "Signature: JWT verification failed for token <NUM>\nExamples: token=1 token=2"
    assert _extract_signature(body) == "JWT verification failed for token <NUM>"


def test_extract_signature_returns_empty_for_un_templated_text(caplog):
    """A chunk without the 'Signature: ' prefix is dual-source state
    (external import or pre-ingestor data). Re-running the masking regex
    over the whole body would silently mis-cluster — wrong signatures
    derived from 'Examples: ...' tokens. Contract: return empty + warn so
    cluster_chunks skips the chunk and we can spot the drift in logs."""
    import logging
    with caplog.at_level(logging.WARNING, logger="repi.retrieval.cluster_view"):
        sig = _extract_signature("INFO: user 1234 logged in from 10.0.0.1")
    assert sig == ""
    assert any("without 'Signature:' prefix" in r.message for r in caplog.records)


def test_returns_empty_for_no_chunks():
    assert cluster_chunks([]) == []


def test_drops_singletons_by_default():
    """A cluster of size 1 isn't a meaningful incident — the timeline panel
    already shows it once. The clusters panel surfaces compressions."""
    chunks = [
        _chunk("Signature: lonely event\nExamples: x", "svc-a", "2026-06-08T14:00:00"),
        _chunk("Signature: repeated\nExamples: y", "svc-a", "2026-06-08T14:01:00"),
        _chunk("Signature: repeated\nExamples: z", "svc-b", "2026-06-08T14:02:00"),
    ]
    out = cluster_chunks(chunks)
    assert [v.signature for v in out] == ["repeated"]


def test_aggregates_count_services_and_time_range():
    chunks = [
        _chunk("Signature: jwt failed\nExamples: a", "auth-service", "2026-06-08T14:02:00"),
        _chunk("Signature: jwt failed\nExamples: b", "auth-service", "2026-06-08T14:04:00"),
        _chunk("Signature: jwt failed\nExamples: c", "api-gateway", "2026-06-08T14:03:00"),
    ]
    out = cluster_chunks(chunks)
    assert len(out) == 1
    v = out[0]
    assert v.signature == "jwt failed"
    assert v.count == 3
    assert v.services == ["api-gateway", "auth-service"]  # sorted, deduped
    assert v.first_ts == "2026-06-08T14:02:00"
    assert v.last_ts == "2026-06-08T14:04:00"


def test_sorted_by_count_descending():
    """Dominant event leads — 'compress thousands of logs into a few
    meaningful incidents' framing requires the biggest cluster first."""
    chunks = (
        [_chunk("Signature: small\nExamples: x", "svc-a", "t1")] * 2 +
        [_chunk("Signature: huge\nExamples: y", "svc-b", "t2")] * 8 +
        [_chunk("Signature: medium\nExamples: z", "svc-c", "t3")] * 4
    )
    out = cluster_chunks(chunks)
    assert [v.signature for v in out] == ["huge", "medium", "small"]
    assert [v.count for v in out] == [8, 4, 2]


def test_missing_timestamps_dont_break_aggregation():
    """Some chunks may have a None timestamp (legacy or bad parse). They
    should still join their signature group; just no time-range contribution."""
    chunks = [
        {"text": "Signature: orphan\nExamples: a", "service": "svc-a", "timestamp": None},
        {"text": "Signature: orphan\nExamples: b", "service": "svc-a", "timestamp": "2026-06-08T14:02:00"},
    ]
    out = cluster_chunks(chunks)
    assert out[0].count == 2
    assert out[0].first_ts == "2026-06-08T14:02:00"
    assert out[0].last_ts == "2026-06-08T14:02:00"
