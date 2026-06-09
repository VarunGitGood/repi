"""Regression for the recency-boost timezone mismatch in rrf.py.

Symptom (PR #70 review): `_dh.now()` is naive UTC per the project's date-handler
convention, but asyncpg returns tz-aware datetimes from `timestamp_start`
(TIMESTAMPTZ). Subtracting naive from aware raises TypeError at runtime when
`recency_boost=True`. The fix normalises both via `DateHandler.to_aware_utc`
before the arithmetic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from repi.retrieval.rrf import RRFRetrievalService


@pytest.mark.asyncio
async def test_recency_boost_handles_tz_aware_timestamps():
    aware_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[("c1", 0.9)])
    vector_store.get_chunks_by_ids = AsyncMock(
        return_value={"c1": {"timestamp_start": aware_ts}}
    )

    fts = MagicMock()
    fts.search = AsyncMock(return_value=[])

    def stub_emb(qs):
        return [[0.0] * 384 for _ in qs]

    svc = RRFRetrievalService(vector_store, fts, stub_emb)
    out = await svc.search("q", top_k=5, recency_boost=True)

    assert len(out) == 1
    assert out[0][0] == "c1"


@pytest.mark.asyncio
async def test_recency_boost_handles_naive_timestamp_strings():
    """`timestamp_start` may also surface as a naive ISO string from older
    test paths or pre-A1 stored data. The same normalisation must work."""
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[("c1", 0.9)])
    vector_store.get_chunks_by_ids = AsyncMock(
        return_value={"c1": {"timestamp_start": "2026-06-01T12:00:00"}}
    )

    fts = MagicMock()
    fts.search = AsyncMock(return_value=[])

    def stub_emb(qs):
        return [[0.0] * 384 for _ in qs]

    svc = RRFRetrievalService(vector_store, fts, stub_emb)
    out = await svc.search("q", top_k=5, recency_boost=True)

    assert len(out) == 1
