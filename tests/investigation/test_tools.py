"""Unit tests for investigation tools."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from repi.investigation.tools import (
    search_logs,
    get_service_summary,
    scan_window,
    _is_valid_uuid,
)


class TestIsValidUuid:
    def test_valid_uuid(self):
        assert _is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_log_text_is_not_uuid(self):
        assert _is_valid_uuid("Auth failure") is False

    def test_empty_string(self):
        assert _is_valid_uuid("") is False

    def test_partial_uuid(self):
        assert _is_valid_uuid("550e8400-e29b") is False


class TestScanWindow:
    @pytest.mark.asyncio
    async def test_returns_error_on_missing_time_params(self):
        result = await scan_window(
            pool=MagicMock(),
            time_from=None,
            time_to=None,
        )
        assert "error" in result
        assert result["logs"] == []
        assert result["summary"] == {}

    @pytest.mark.asyncio
    async def test_returns_empty_results_when_no_chunks(self):
        mock_pool = AsyncMock()
        mock_pool.fetch.return_value = []
        result = await scan_window(
            pool=mock_pool,
            time_from="2026-04-30T22:00:00",
            time_to="2026-04-30T22:05:00",
        )
        assert result["logs"] == []
        assert result["summary"] == {}
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_summary_covers_all_log_services(self):
        from datetime import datetime
        c1 = "550e8400-e29b-41d4-a716-446655440001"
        c2 = "550e8400-e29b-41d4-a716-446655440002"
        summary_rows = [
            {"source_service": "svc-a", "errors": 1, "warnings": 0, "first_error": datetime(2026, 4, 30, 22, 0)},
            {"source_service": "svc-b", "errors": 0, "warnings": 1, "first_error": None},
        ]
        log_rows = [
            {"chunk_id": c1, "source_service": "svc-a", "log_level": "ERROR", "timestamp_start": datetime(2026, 4, 30, 22, 0), "text": "err"},
            {"chunk_id": c2, "source_service": "svc-b", "log_level": "WARNING", "timestamp_start": datetime(2026, 4, 30, 22, 0, 5), "text": "warn"},
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch.side_effect = [summary_rows, log_rows]
        result = await scan_window(
            pool=mock_pool,
            time_from="2026-04-30T22:00:00",
            time_to="2026-04-30T22:05:00",
        )
        log_services = {entry["service"] for entry in result["logs"]}
        for svc in log_services:
            assert svc in result["summary"], f"service {svc!r} in logs but missing from summary"


class TestSearchLogsReturnShape:
    """Ensure search_logs always returns a list of dicts with required fields."""

    REQUIRED_FIELDS = {"chunk_id", "service", "level", "timestamp_start", "text", "score"}

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self, mock_rrf_service):
        results = await search_logs(rrf_service=mock_rrf_service, query="auth error", service="auth-service")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_each_result_has_required_fields(self, mock_rrf_service):
        results = await search_logs(rrf_service=mock_rrf_service, query="auth error", service="auth-service")
        for result in results:
            missing = self.REQUIRED_FIELDS - result.keys()
            assert not missing, f"Result missing fields: {missing}"

    @pytest.mark.asyncio
    async def test_empty_query_returns_list(self, mock_rrf_service):
        results = await search_logs(rrf_service=mock_rrf_service, query="", service="auth-service")
        assert isinstance(results, list)

    @pytest.fixture
    def mock_rrf_service(self):
        mock = AsyncMock()
        chunk_id = "550e8400-e29b-41d4-a716-446655440000"
        chunks = {
            chunk_id: {
                "source_service": "auth-service",
                "log_level": "ERROR",
                "timestamp_start": "2026-04-28T00:44:00",
                "timestamp_end": "2026-04-28T00:44:01",
                "text": "2026-04-28 00:44:00 ERROR auth-service Auth failure"
            }
        }
        mock.vector_store = AsyncMock()
        mock.vector_store.get_chunks_by_ids.return_value = chunks
        mock.vector_store.filter_search.return_value = [(chunk_id, 1.0)]
        mock.search.return_value = [(chunk_id, 0.9)]
        return mock
