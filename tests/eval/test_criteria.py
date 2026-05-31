"""Tests for eval.criteria — verifies criteria extraction from all 3 expected.json shapes."""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from eval.criteria import build_criteria, active_criterion_names

ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def dataset_1_expected():
    path = ROOT / "eval/dataset_1_cascading_inventory_migration/expected.json"
    return json.loads(path.read_text())


@pytest.fixture
def dataset_2_expected():
    path = ROOT / "eval/dataset_2_insufficient_logging/expected.json"
    return json.loads(path.read_text())


@pytest.fixture
def dataset_3_expected():
    path = ROOT / "eval/dataset_3_jwt_key_rotation_noise/expected.json"
    return json.loads(path.read_text())


class TestActiveCriterionNames:
    def test_dataset_1_criteria(self, dataset_1_expected):
        names = active_criterion_names(dataset_1_expected)
        assert "trigger_identification" in names
        assert "root_cause_accuracy" in names
        assert "propagation_chain" in names
        assert "red_herring_handling" in names
        assert "confidence_calibration" in names
        assert "gap_awareness" not in names

    def test_dataset_2_criteria(self, dataset_2_expected):
        names = active_criterion_names(dataset_2_expected)
        assert "trigger_identification" in names
        assert "confidence_calibration" in names
        assert "gap_awareness" in names
        assert "hallucination_avoidance" in names
        assert "red_herring_handling" in names
        assert "propagation_chain" not in names

    def test_dataset_3_criteria(self, dataset_3_expected):
        names = active_criterion_names(dataset_3_expected)
        assert "trigger_identification" in names
        assert "root_cause_accuracy" in names
        assert "propagation_chain" in names
        assert "red_herring_handling" in names
        assert "hallucination_avoidance" in names


class TestBuildCriteria:
    def test_dataset_1_contains_trigger_service(self, dataset_1_expected):
        text = build_criteria(dataset_1_expected)
        assert "inventory-svc" in text

    def test_dataset_1_contains_root_cause_terms(self, dataset_1_expected):
        text = build_criteria(dataset_1_expected)
        assert "migration" in text
        assert "warehouse_id" in text

    def test_dataset_1_contains_red_herrings(self, dataset_1_expected):
        text = build_criteria(dataset_1_expected)
        assert "pricing-svc" in text
        assert "payment-svc" in text

    def test_dataset_2_contains_gap_criteria(self, dataset_2_expected):
        text = build_criteria(dataset_2_expected)
        assert "gap_awareness" in text
        assert "no memory" in text.lower() or "SIGKILL" in text

    def test_dataset_2_contains_hallucination_criteria(self, dataset_2_expected):
        text = build_criteria(dataset_2_expected)
        assert "hallucination_avoidance" in text
        assert "memory leak" in text

    def test_dataset_2_contains_ruled_out_consider(self, dataset_2_expected):
        text = build_criteria(dataset_2_expected)
        assert "red_herring_handling" in text
        assert "code crash" in text
        assert "deadlock" in text

    def test_dataset_2_confidence_must_be_low(self, dataset_2_expected):
        text = build_criteria(dataset_2_expected)
        assert "low" in text

    def test_dataset_3_trigger_accepts_multiple(self, dataset_3_expected):
        text = build_criteria(dataset_3_expected)
        assert "auth-svc" in text
        assert "JWT" in text or "key rotation" in text.lower() or "key_id=k-2026-05" in text

    def test_dataset_3_not_assert_as_root_cause(self, dataset_3_expected):
        text = build_criteria(dataset_3_expected)
        assert "cache-svc" in text
        assert "billing-svc" in text

    def test_empty_expected_produces_empty(self):
        text = build_criteria({})
        assert text == ""

    def test_minimal_expected_only_confidence(self):
        expected = {"expected_answer": {"confidence": "high"}}
        text = build_criteria(expected)
        assert "confidence_calibration" in text
        assert "high" in text
