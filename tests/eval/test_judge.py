"""Tests for eval.judge — LLMJudge scoring, response parsing, and precheck."""
from __future__ import annotations
import json
from unittest.mock import AsyncMock

import pytest

from eval.judge import (
    LLMJudge,
    deterministic_precheck,
    _parse_judge_response,
    PASS_THRESHOLD,
)
from eval.results import JudgeResult, CriterionScore


# ─── deterministic_precheck ─────────────────────────────────────────────────

class TestDeterministicPrecheck:
    def test_empty_answer_fails(self):
        errors = deterministic_precheck({})
        assert errors is not None
        assert any("Missing" in e or "empty" in e.lower() for e in errors)

    def test_missing_confidence_fails(self):
        answer = {"root_cause": "something", "affected_services": ["a"]}
        errors = deterministic_precheck(answer)
        assert errors is not None
        assert any("confidence" in e for e in errors)

    def test_invalid_confidence_fails(self):
        answer = {
            "confidence": "very_high",
            "root_cause": "something",
            "affected_services": ["a"],
        }
        errors = deterministic_precheck(answer)
        assert errors is not None
        assert any("confidence" in e for e in errors)

    def test_valid_answer_passes(self):
        answer = {
            "confidence": "high",
            "root_cause": "migration broke things",
            "affected_services": ["svc-a"],
            "trigger_event": {},
            "propagation_chain": [],
            "ruled_out_hypotheses": [],
            "assumptions": [],
            "gaps": [],
            "incident_window": {},
        }
        errors = deterministic_precheck(answer)
        assert errors is None


# ─── _parse_judge_response ──────────────────────────────────────────────────

class TestParseJudgeResponse:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "scores": [
                {"name": "trigger_identification", "score": 0.9, "explanation": "Correct service"},
                {"name": "root_cause_accuracy", "score": 0.7, "explanation": "Mostly right"},
            ]
        })
        result = _parse_judge_response(
            raw, "test_ds", "mistral-large", "gpt-4o",
            ["trigger_identification", "root_cause_accuracy"],
        )
        assert isinstance(result, JudgeResult)
        assert result.dataset == "test_ds"
        assert result.aggregate_score == 0.8
        assert len(result.criteria) == 2

    def test_handles_markdown_fences(self):
        raw = "```json\n" + json.dumps({
            "scores": [{"name": "confidence_calibration", "score": 1.0, "explanation": "ok"}]
        }) + "\n```"
        result = _parse_judge_response(
            raw, "ds", "model", "judge",
            ["confidence_calibration"],
        )
        assert result.criteria[0].score == 1.0

    def test_fills_missing_criteria_with_zero(self):
        raw = json.dumps({
            "scores": [
                {"name": "trigger_identification", "score": 0.8, "explanation": "ok"},
            ]
        })
        result = _parse_judge_response(
            raw, "ds", "model", "judge",
            ["trigger_identification", "root_cause_accuracy"],
        )
        assert len(result.criteria) == 2
        missing = [c for c in result.criteria if c.name == "root_cause_accuracy"]
        assert missing[0].score == 0.0
        assert "did not return" in missing[0].explanation.lower()

    def test_clamps_scores(self):
        raw = json.dumps({
            "scores": [
                {"name": "x", "score": 1.5, "explanation": "over"},
                {"name": "y", "score": -0.3, "explanation": "under"},
            ]
        })
        result = _parse_judge_response(raw, "ds", "m", "j", ["x", "y"])
        scores = {c.name: c.score for c in result.criteria}
        assert scores["x"] == 1.0
        assert scores["y"] == 0.0


# ─── LLMJudge.score ─────────────────────────────────────────────────────────

class TestLLMJudge:
    @pytest.mark.asyncio
    async def test_score_calls_llm_and_returns_result(self):
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

        result = await judge.score(answer, expected, "test_ds", "model-under-test")

        assert isinstance(result, JudgeResult)
        assert result.judge_model == "test-judge-model"
        assert result.model_under_test == "model-under-test"
        assert result.aggregate_score > 0
        mock_llm.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_model_name_property(self):
        mock_llm = AsyncMock()
        mock_llm.model_name = "gpt-4o"
        judge = LLMJudge(mock_llm)
        assert judge.model_name == "gpt-4o"


# ─── Constants ───────────────────────────────────────────────────────────────

class TestConstants:
    def test_pass_threshold_is_0_8(self):
        assert PASS_THRESHOLD == 0.8
