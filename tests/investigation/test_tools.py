"""Unit tests for investigation tools."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.app.investigation.tools import (
    search_logs,
    get_service_summary,
    find_co_occurring,
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


class TestFindCoOccurring:
    @pytest.mark.asyncio
    async def test_rejects_non_uuid_chunk_ids(self):
        result = await find_co_occurring(
            pool=MagicMock(), # not used if invalid
            chunk_ids=["Auth failure", "some log text"],
            window_seconds=300,
        )
        assert "warning" in result
        assert result["results"] == []
        assert "chunk_id" in result["warning"].lower() or "uuid" in result["warning"].lower()

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_co_occurring(self):
        mock_pool = AsyncMock()
        mock_pool.fetch.return_value = []
        result = await find_co_occurring(
            pool=mock_pool,
            chunk_ids=["550e8400-e29b-41d4-a716-446655440000"],
            window_seconds=300,
        )
        assert result == {"results": []}


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
        from src.app.models.domain import SearchResult
        mock = AsyncMock()
        # Mock vector_store
        mock.vector_store = AsyncMock()
        mock.vector_store.get_chunks_by_ids.return_value = {
            "550e8400-e29b-41d4-a716-446655440000": {
                "source_service": "auth-service",
                "log_level": "ERROR",
                "timestamp_start": "2026-04-28T00:44:00",
                "timestamp_end": "2026-04-28T00:44:01",
                "text": "2026-04-28 00:44:00 ERROR auth-service Auth failure"
            }
        }
        mock.search.return_value = [
            ("550e8400-e29b-41d4-a716-446655440000", 0.9)
        ]
        return mock
