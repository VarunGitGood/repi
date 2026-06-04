"""Unit tests for the LLM response parser."""
from __future__ import annotations

import pytest
import numpy as np
from repi.investigation.react_loop import parse_llm_response  # re-export of json_utils.parse_llm_response
from repi.llm.json_utils import _extract_json_objects
from repi.models.domain import SearchResult

class TestExtractJsonObjects:
    def test_single_object(self):
        text = '{"thought": "hello", "action": {"tool": "search_logs"}}'
        result = _extract_json_objects(text)
        assert len(result) == 1
        assert result[0]["thought"] == "hello"

    def test_two_split_objects(self):
        text = '{"thought": "reasoning"}\n\n{"action": {"tool": "search_logs", "args": {}}}'
        result = _extract_json_objects(text)
        assert len(result) == 2

    def test_object_with_markdown_fence(self):
        text = '```json\n{"thought": "hello"}\n```'
        # _extract_json_objects receives pre-stripped text
        stripped = text.replace("```json", "").replace("```", "").strip()
        result = _extract_json_objects(stripped)
        assert len(result) == 1

    def test_nested_objects_count_as_one(self):
        text = '{"thought": "x", "action": {"tool": "y", "args": {"k": "v"}}}'
        result = _extract_json_objects(text)
        assert len(result) == 1

    def test_empty_string(self):
        result = _extract_json_objects("")
        assert result == []

    def test_no_json(self):
        result = _extract_json_objects("just plain text, no json here")
        assert result == []


class TestParseLlmResponse:
    def test_parses_single_clean_json(self):
        raw = '{"thought": "I need to search", "action": {"tool": "search_logs", "args": {"query": "error"}}}'
        result = parse_llm_response(raw)
        assert result["thought"] == "I need to search"
        assert result["action"]["tool"] == "search_logs"

    def test_parses_split_json_objects(self):
        raw = '''{"thought": "first think"}

{"action": {"tool": "get_service_summary", "args": {"service": "auth-service"}}}'''
        result = parse_llm_response(raw)
        assert "thought" in result
        assert "action" in result
        assert result["action"]["tool"] == "get_service_summary"

    def test_parses_markdown_fenced_json(self):
        raw = '```json\n{"thought": "thinking", "answer": {"summary": "done"}}\n```'
        result = parse_llm_response(raw)
        assert result["thought"] == "thinking"
        assert "answer" in result

    def test_raises_on_no_json(self):
        with pytest.raises((ValueError, Exception)):
            parse_llm_response("This is just plain text with no JSON at all.")

    def test_parses_final_answer_format(self):
        raw = '''{
          "thought": "I have enough evidence",
          "answer": {
            "summary": "Auth service failed due to expired token",
            "root_cause": "Token expiry",
            "causal_chain": ["token expired", "auth failed"],
            "impacted_services": ["auth-service"],
            "confidence": "high",
            "confidence_reasoning": "Direct evidence from logs"
          }
        }'''
        result = parse_llm_response(raw)
        assert result["answer"]["confidence"] == "high"


class TestPydanticEmbeddingCoercion:
    """Ensure numpy arrays are coerced to list[float] by the validator."""

    def test_numpy_array_coerced(self):
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        result = SearchResult(
            chunk_id="550e8400-e29b-41d4-a716-446655440000",
            score=0.9,
            text="test log",
            metadata={},
            embedding=embedding,
        )
        assert isinstance(result.embedding, list)
        assert all(isinstance(x, float) for x in result.embedding)

    def test_list_float_passes_through(self):
        embedding = [0.1, 0.2, 0.3]
        result = SearchResult(
            chunk_id="550e8400-e29b-41d4-a716-446655440000",
            score=0.9,
            text="test log",
            metadata={},
            embedding=embedding,
        )
        assert result.embedding == [0.1, 0.2, 0.3]

    def test_none_embedding_allowed(self):
        result = SearchResult(
            chunk_id="550e8400-e29b-41d4-a716-446655440000",
            score=0.9,
            text="test log",
            metadata={},
            embedding=None,
        )
        assert result.embedding is None
