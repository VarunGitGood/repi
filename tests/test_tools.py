import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
import json

from repi.investigation.tools import (
    search_logs,
    get_timeline,
    find_co_occurring,
    get_service_summary
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
async def test_find_co_occurring():
    pool = MagicMock()
    c1 = "550e8400-e29b-41d4-a716-446655440001"
    c2 = "550e8400-e29b-41d4-a716-446655440002"
    pool.fetch = AsyncMock(return_value=[
        {"chunk_id": c1, "source_service": "s1", "log_level": "ERROR", "timestamp_start": datetime(2026,4,1,10,0), "text": "err1"},
        {"chunk_id": c2, "source_service": "s2", "log_level": "ERROR", "timestamp_start": datetime(2026,4,1,10,0,5), "text": "err2"},
    ])

    results = await find_co_occurring(pool, time_from="2026-04-01T09:55:00", time_to="2026-04-01T10:05:00")

    assert results["total"] == 2
    assert results["results"][0]["chunk_id"] == c1
    assert results["results"][0]["service"] == "s1"
    assert results["results"][1]["chunk_id"] == c2

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
