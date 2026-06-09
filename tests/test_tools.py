import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
import json

from repi.investigation.tools import (
    search_logs,
    get_timeline,
    scan_window,
    get_service_summary,
    find_logs_by_id,
)
from repi.models.filters import RetrievalFilters

@pytest.mark.asyncio
async def test_search_logs():
    # Mock RRF Service
    rrf_service = MagicMock()
    rrf_service.search = AsyncMock(return_value=[("chunk_1", 0.9), ("chunk_2", 0.8)])
    rrf_service.vector_store.get_chunks_by_ids = AsyncMock(return_value={
        "chunk_1": {"source_service": "auth", "log_level": "ERROR", "text": "failed login", "timestamp_start": datetime(2026, 4, 1, 10, 0)},
        "chunk_2": {"source_service": "auth", "log_level": "INFO", "text": "user logged in", "timestamp_start": datetime(2026, 4, 1, 10, 1)}
    })

    results = await search_logs(rrf_service, query="failed", service="auth")

    assert len(results) == 2
    assert results[0]["chunk_id"] == "chunk_1"
    assert results[0]["service"] == "auth"
    assert results[0]["score"] == 0.9
    
    # Verify filters were passed correctly
    rrf_service.search.assert_called_once()
    filters = rrf_service.search.call_args.kwargs["filters"]
    assert isinstance(filters, RetrievalFilters)
    assert filters.source_service == "auth"

@pytest.mark.asyncio
async def test_get_timeline():
    # Mock Pool
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[
        {"chunk_id": "c1", "source_service": "s1", "log_level": "INFO", "timestamp_start": datetime(2026,4,1,10,0), "text": "t1"},
        {"chunk_id": "c2", "source_service": "s1", "log_level": "ERROR", "timestamp_start": datetime(2026,4,1,10,1), "text": "t2"}
    ])

    results = await get_timeline(pool, ["c1", "c2"])

    assert len(results) == 2
    assert results[0]["chunk_id"] == "c1"
    assert results[1]["timestamp"] == "2026-04-01T10:01:00"

@pytest.mark.asyncio
async def test_scan_window():
    pool = MagicMock()
    c1 = "550e8400-e29b-41d4-a716-446655440001"
    c2 = "550e8400-e29b-41d4-a716-446655440002"
    summary_rows = [
        {"source_service": "s1", "errors": 1, "warnings": 0, "first_error": datetime(2026,4,1,10,0)},
        {"source_service": "s2", "errors": 1, "warnings": 0, "first_error": datetime(2026,4,1,10,0,5)},
    ]
    log_rows = [
        {"chunk_id": c1, "source_service": "s1", "log_level": "ERROR", "timestamp_start": datetime(2026,4,1,10,0), "text": "err1"},
        {"chunk_id": c2, "source_service": "s2", "log_level": "ERROR", "timestamp_start": datetime(2026,4,1,10,0,5), "text": "err2"},
    ]
    # 3 fetches now: summary, logs, pre_context (both services have first_error)
    pool.fetch = AsyncMock(side_effect=[summary_rows, log_rows, []])

    results = await scan_window(pool, time_from="2026-04-01T09:55:00", time_to="2026-04-01T10:05:00")

    assert results["total"] == 2
    assert results["logs"][0]["chunk_id"] == c1
    assert results["logs"][0]["service"] == "s1"
    assert results["logs"][1]["chunk_id"] == c2
    assert "s1" in results["summary"]
    assert results["summary"]["s1"]["errors"] == 1

@pytest.mark.asyncio
async def test_get_service_summary():
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={
        "total_chunks": 100,
        "unique_requests": 50,
        "error_count": 5,
        "warning_count": 10,
        "info_count": 85,
        "earliest": datetime(2026, 4, 1, 9, 0),
        "latest": datetime(2026, 4, 1, 10, 0)
    })

    result = await get_service_summary(pool, "auth-service")

    assert result["service"] == "auth-service"
    assert result["total_chunks"] == 100
    assert result["error_count"] == 5
    assert result["earliest"] == "2026-04-01T09:00:00"


@pytest.mark.asyncio
async def test_find_logs_by_id_returns_similarity_and_filters_threshold():
    """find_logs_by_id surfaces a similarity score and drops rows below
    min_similarity. The DB returns ranked rows (sim DESC); the Python layer
    enforces the floor and reshapes."""
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[
        # ILIKE substring hit → sim 1.0 (exact match)
        {"chunk_id": "c1", "source_service": "auth-service", "log_level": "ERROR",
         "timestamp_start": datetime(2026, 4, 1, 10, 0), "text": "ch_3MX8K2 failed",
         "sim": 1.0},
        # Fuzzy word-similarity hit above threshold
        {"chunk_id": "c2", "source_service": "auth-service", "log_level": "ERROR",
         "timestamp_start": datetime(2026, 4, 1, 10, 1), "text": "ch_3MX8K3 charge denied",
         "sim": 0.75},
        # Fuzzy hit below threshold — must be dropped.
        {"chunk_id": "c3", "source_service": "auth-service", "log_level": "INFO",
         "timestamp_start": datetime(2026, 4, 1, 10, 2), "text": "loosely related token",
         "sim": 0.42},
    ])

    out = await find_logs_by_id(pool, "ch_3MX8K2", top_k=10, min_similarity=0.6)
    chunk_ids = [r["chunk_id"] for r in out]
    assert chunk_ids == ["c1", "c2"]  # c3 below floor
    assert out[0]["similarity"] == 1.0
    assert out[1]["similarity"] == 0.75


@pytest.mark.asyncio
async def test_find_logs_by_id_empty_input_short_circuits():
    pool = MagicMock()
    pool.fetch = AsyncMock()
    assert await find_logs_by_id(pool, "") == []
    assert await find_logs_by_id(pool, "   ") == []
    pool.fetch.assert_not_called()
