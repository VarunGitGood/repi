"""Tests for eval.judge after Issue #49 refactor:
- precheck-as-gate is gone; the precheck function still exists but is advisory
- parse_llm_response is shared with the loop (repi.llm.json_utils)
- judge retries once on parse failure
- judge tracks last_parse_attempts so the runner can report it
"""
from __future__ import annotations
import json
from unittest.mock import AsyncMock

import pytest

from eval.judge import (
    LLMJudge,
    deterministic_precheck,
    PASS_THRESHOLD,
    _parse_judge_payload,
    _scores_from_parsed,
)
from eval.results import JudgeResult, CriterionScore


# ─── deterministic_precheck (kept as advisory, not gating) ───────────────────

class TestDeterministicPrecheckAdvisory:
    def test_function_still_exists(self):
        """Kept so external callers don't break, but it's no longer in the path."""
        errors = deterministic_precheck({})
        assert errors is not None  # still flags empties
        assert any("empty" in e.lower() or "missing" in e.lower() for e in errors)

    def test_valid_answer_returns_none(self):
        answer = {
            "confidence": "high",
            "root_cause": "x",
            "affected_services": ["svc-a"],
        }
        assert deterministic_precheck(answer) is None


# ─── _parse_judge_payload (uses shared parser) ────────────────────────────────

class TestParseJudgePayload:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "scores": [
                {"name": "trigger_identification", "score": 0.9, "explanation": "ok"},
            ]
        })
        parsed = _parse_judge_payload(raw)
        assert parsed is not None
        assert parsed["scores"][0]["score"] == 0.9

    def test_handles_markdown_fences(self):
        raw = "```json\n" + json.dumps({"scores": [{"name": "x", "score": 1.0, "explanation": "ok"}]}) + "\n```"
        parsed = _parse_judge_payload(raw)
        assert parsed is not None

    def test_invalid_json_returns_none(self):
        assert _parse_judge_payload("not valid at all") is None
        assert _parse_judge_payload("") is None


class TestScoresFromParsed:
    def test_clamps_to_unit_interval(self):
        parsed = {"scores": [
            {"name": "x", "score": 1.5, "explanation": "over"},
            {"name": "y", "score": -0.3, "explanation": "under"},
        ]}
        scored = _scores_from_parsed(parsed, ["x", "y"])
        assert scored["x"].score == 1.0
        assert scored["y"].score == 0.0

    def test_extra_criteria_dropped(self):
        parsed = {"scores": [
            {"name": "x", "score": 0.9, "explanation": "ok"},
            {"name": "extra", "score": 0.5, "explanation": "skip"},
        ]}
        scored = _scores_from_parsed(parsed, ["x"])
        assert set(scored.keys()) == {"x"}


# ─── LLMJudge.score ─────────────────────────────────────────────────────────


class TestLLMJudgeScore:
    @pytest.mark.asyncio
    async def test_happy_path_no_retry(self):
        mock_llm = AsyncMock()
        mock_llm.model_name = "test-judge-model"
        mock_llm.complete.return_value = json.dumps({
            "scores": [
                {"name": "trigger_identification", "score": 0.9, "explanation": "good"},
                {"name": "root_cause_accuracy", "score": 0.8, "explanation": "ok"},
                {"name": "confidence_calibration", "score": 1.0, "explanation": "correct"},
            ]
        })

        judge = LLMJudge(mock_llm)
        expected = {
            "expected_answer": {
                "trigger_event": {"service": "svc-a"},
                "root_cause_must_mention": ["migration"],
                "confidence": "high",
            }
        }
        answer = {
            "confidence": "high",
            "root_cause": "migration caused it",
            "affected_services": ["svc-a"],
            "trigger_event": {"service": "svc-a"},
        }

        result = await judge.score(answer, expected, "test_ds", "mut")
        assert isinstance(result, JudgeResult)
        assert result.aggregate_score > 0
        assert judge.last_parse_attempts == 1
        assert mock_llm.complete.await_count == 1

    @pytest.mark.asyncio
    async def test_parser_retries_once_on_invalid_json(self):
        mock_llm = AsyncMock()
        mock_llm.model_name = "judge-x"
        # First reply: garbage. Second reply: valid.
        mock_llm.complete.side_effect = [
            "totally garbage not json",
            json.dumps({
                "scores": [{"name": "trigger_identification", "score": 0.7, "explanation": "ok"}],
            }),
        ]

        judge = LLMJudge(mock_llm)
        expected = {"expected_answer": {"trigger_event": {"service": "x"}}}
        answer = {"confidence": "low", "root_cause": "x", "affected_services": ["x"]}

        result = await judge.score(answer, expected, "ds", "mut")
        assert judge.last_parse_attempts == 2
        assert mock_llm.complete.await_count == 2
        # The retry succeeded -> a real score is in the result.
        tid = next(c for c in result.criteria if c.name == "trigger_identification")
        assert tid.score == 0.7

    @pytest.mark.asyncio
    async def test_two_unparseable_replies_record_zero_scores(self):
        mock_llm = AsyncMock()
        mock_llm.model_name = "judge-x"
        mock_llm.complete.side_effect = ["garbage one", "garbage two"]

        judge = LLMJudge(mock_llm)
        expected = {"expected_answer": {"trigger_event": {"service": "x"}}}
        answer = {"confidence": "low", "root_cause": "x", "affected_services": ["x"]}

        result = await judge.score(answer, expected, "ds", "mut")
        assert judge.last_parse_attempts == 2
        assert all(c.score == 0.0 for c in result.criteria)
        # Explanation reflects the retry failure rather than "not scored".
        assert any("not valid JSON" in c.explanation.lower() or "json" in c.explanation.lower()
                   for c in result.criteria)


class TestConstants:
    def test_pass_threshold_is_0_8(self):
        assert PASS_THRESHOLD == 0.8
