"""Tests for ReactInvestigationLoop._extract_chunks nested traversal.

scan_window returns {logs: [...], pre_context_logs: [...], summary: {...}} —
the chunk-bearing entries are nested under the list keys, so the extractor
must recurse to pick them up.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from repi.investigation.react_loop import ReactInvestigationLoop


def _bare_loop() -> ReactInvestigationLoop:
    """Construct a loop instance with stub dependencies — we only need _extract_chunks."""
    return ReactInvestigationLoop(
        llm=MagicMock(),
        tools={},
        known_services=[],
        pool=None,
        store=None,
    )


class TestExtractChunksNested:
    def test_traverses_logs_and_pre_context_lists(self):
        loop = _bare_loop()
        tool_result = {
            "logs": [{"chunk_id": "a"}, {"chunk_id": "b"}],
            "pre_context_logs": [{"chunk_id": "c"}],
            "summary": {"svc": {"errors": 1}},
            "total": 2,
            "window": ["t1", "t2"],
        }

        chunks = loop._extract_chunks(tool_result)

        ids = [c["chunk_id"] for c in chunks]
        assert sorted(ids) == ["a", "b", "c"]

    def test_dedupes_chunk_ids_across_lists(self):
        """The same chunk_id appearing in both `logs` and `pre_context_logs` is collected once."""
        loop = _bare_loop()
        tool_result = {
            "logs": [{"chunk_id": "a"}, {"chunk_id": "a"}],
            "pre_context_logs": [{"chunk_id": "a"}],
        }

        chunks = loop._extract_chunks(tool_result)

        assert [c["chunk_id"] for c in chunks] == ["a"]

    def test_top_level_dict_with_chunk_id_still_works(self):
        """The legacy single-chunk dict shape (top-level chunk_id) is still picked up."""
        loop = _bare_loop()
        result = loop._extract_chunks({"chunk_id": "x", "text": "hi"})
        assert [c["chunk_id"] for c in result] == ["x"]

    def test_top_level_list_still_works(self):
        """search_logs returns a list of dicts — the existing shape must keep working."""
        loop = _bare_loop()
        result = loop._extract_chunks([{"chunk_id": "x"}, {"chunk_id": "y"}])
        assert [c["chunk_id"] for c in result] == ["x", "y"]

    def test_non_chunk_list_values_are_ignored(self):
        """Lists that don't contain dicts-with-chunk_id shouldn't crash the walker."""
        loop = _bare_loop()
        result = loop._extract_chunks({
            "errors": ["string entry", 42, None],
            "logs": [{"chunk_id": "x"}],
        })
        assert [c["chunk_id"] for c in result] == ["x"]
