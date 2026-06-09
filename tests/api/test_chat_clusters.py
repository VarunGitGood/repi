"""Verify the /chat `done` event carries a `clusters` payload.

We test the serialization shape — cluster_chunks itself is exercised
exhaustively in tests/retrieval/test_cluster_view.py. The chat path
is a streaming SSE handler; full end-to-end coverage lives in the
eval suite.
"""
from __future__ import annotations

from repi.retrieval.cluster_view import cluster_chunks


def _chunk(sig: str, service: str, ts: str):
    return {
        "chunk_id": "id-" + sig,
        "service": service,
        "level": "ERROR",
        "timestamp": ts,
        "text": f"Signature: {sig}\nExamples: x",
    }


def test_chat_done_clusters_payload_shape():
    """The done event's `clusters` key is a list[dict] with the exact
    field names the UI panel binds to. This is the contract that
    web/components/chat/EventClusters.tsx renders against."""
    chunks = [
        _chunk("jwt failed", "auth-service", "2026-06-08T14:02:00"),
        _chunk("jwt failed", "auth-service", "2026-06-08T14:03:00"),
        _chunk("jwt failed", "api-gateway", "2026-06-08T14:04:00"),
        _chunk("db timeout", "payments-api", "2026-06-08T14:05:00"),
        _chunk("db timeout", "payments-api", "2026-06-08T14:06:00"),
    ]

    # Mirror the in-handler projection from repi/api/chat.py
    clusters_payload = [
        {
            "signature": v.signature,
            "count": v.count,
            "services": v.services,
            "first_ts": v.first_ts,
            "last_ts": v.last_ts,
        }
        for v in cluster_chunks(chunks)
    ]

    assert len(clusters_payload) == 2
    # Sorted by count desc.
    assert clusters_payload[0]["signature"] == "jwt failed"
    assert clusters_payload[0]["count"] == 3
    assert clusters_payload[0]["services"] == ["api-gateway", "auth-service"]
    assert clusters_payload[1]["signature"] == "db timeout"
    assert clusters_payload[1]["count"] == 2


def test_chat_done_clusters_empty_when_all_singletons():
    """No cluster has ≥2 hits → empty list. The UI can hide the panel
    entirely; we don't yield a sentinel."""
    chunks = [
        _chunk("a", "svc-a", "2026-06-08T14:02:00"),
        _chunk("b", "svc-b", "2026-06-08T14:03:00"),
    ]
    payload = [
        {"signature": v.signature, "count": v.count}
        for v in cluster_chunks(chunks)
    ]
    assert payload == []
