"""Unit tests for the /chat endpoint's pure pieces.

Full endpoint coverage is via live smoke + the eval suite — mocking the
SQLModel async session + retrieval service + LLM provider for a streaming
SSE handler buys little signal for a lot of mock plumbing.
"""
from __future__ import annotations

import json

from repi.api.chat import _chat_confidence, _sse


def test_sse_envelope_shape():
    """SSE matches `/investigations/{id}/stream` style: `data: {…}\\n\\n`."""
    out = _sse("delta", {"text": "hello"})
    assert out.startswith("data: ")
    assert out.endswith("\n\n")
    body = json.loads(out[len("data: "):].strip())
    assert body == {"type": "delta", "data": {"text": "hello"}}


def test_chat_confidence_empty_evidence():
    assert _chat_confidence([], entities=[]) == "low"


def test_chat_confidence_entity_anchored_but_absent():
    """User anchored on a Stripe-style charge ID but no chunk contains it."""
    chunks = [{"text": "unrelated log line", "chunk_id": "c1"}]
    assert _chat_confidence(chunks, entities=["ch_3MX8K2eZvKYlo2C1aBcDeFg"]) == "low"


def test_chat_confidence_entity_present_in_chunk():
    chunks = [{"text": "ch_3MX8K2eZvKYlo2C1aBcDeFg failed", "chunk_id": "c1"}]
    assert _chat_confidence(chunks, entities=["ch_3MX8K2eZvKYlo2C1aBcDeFg"]) == "medium"


def test_chat_confidence_no_entity_constraint():
    """Without resolved entities, having any chunks gives medium (chat never high)."""
    chunks = [{"text": "x", "chunk_id": "c1"}, {"text": "y", "chunk_id": "c2"}]
    assert _chat_confidence(chunks, entities=[]) == "medium"


def test_chat_confidence_case_insensitive_entity_match():
    chunks = [{"text": "TRACE 4BF92F3577B34DA6A3CE929D0E0E4736 served", "chunk_id": "c1"}]
    # User typed lowercase, log emitted uppercase.
    assert _chat_confidence(chunks, entities=["4bf92f3577b34da6a3ce929d0e0e4736"]) == "medium"
