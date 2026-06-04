"""Tests for the compile-answer module (Issue #48 Priority 2 / 4 / 5)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from repi.investigation.compiler import (
    compile_answer,
    synthesize_answer,
    CompileResult,
)
from repi.investigation.schema import enforce_floors


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _evidence(n: int = 2) -> list[dict]:
    return [
        {
            "chunk_id": f"c{i}",
            "service": ["svc-a", "svc-b"][i % 2],
            "timestamp": f"2026-01-0{i+1}T00:00:00Z",
            "level": "ERROR" if i == 0 else "INFO",
            "message": f"event {i}",
        }
        for i in range(n)
    ]


def _ledger(*tools: str) -> dict[str, dict]:
    return {
        f"{t}::0": {"tool_name": t, "args": {"q": "x"}, "result": []}
        for t in tools
    }


class _ResolvedIntent:
    def __init__(self, tf="2026-01-01T00:00:00", tt="2026-01-02T00:00:00", assumed=None):
        self.time_from = tf
        self.time_to = tt
        self.services = []
        self.assumed = assumed or []


def _make_llm(*responses):
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=list(responses))
    return llm


# ─── compile_answer happy path ───────────────────────────────────────────────


class TestCompileHappyPath:
    @pytest.mark.asyncio
    async def test_compiler_returns_validated_answer_on_first_try(self):
        good_answer = {
            "confidence": "low",
            "affected_services": ["svc-a", "svc-b"],
            "trigger_event": {"chunk_id": "c0", "service": "svc-a", "timestamp": "x", "log_line": "x"},
            # validate_answer requires propagation_chain when affected_services has >=2 entries.
            "propagation_chain": [{"chunk_id": "c1", "service": "svc-b", "ts": "x", "what": "x"}],
            "ruled_out_hypotheses": [{"hypothesis": "h1", "why_ruled_out": "no evidence"}],
            "assumptions": [],
            "gaps": ["fixture"],
            "incident_window": {"start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00"},
            "root_cause": "unable to determine",
        }
        llm = _make_llm(json.dumps(good_answer))

        result = await compile_answer(
            llm=llm,
            query="why",
            resolved_intent=_ResolvedIntent(),
            evidence=_evidence(2),
            tool_ledger=_ledger("search_logs"),
            recent_thoughts=["thinking..."],
        )

        assert isinstance(result, CompileResult)
        assert result.source == "llm"
        assert result.attempts == 1
        assert result.answer["confidence"] == "low"
        assert "svc-a" in result.answer["affected_services"]


# ─── Validation retry ────────────────────────────────────────────────────────


class TestCompileValidationRetry:
    @pytest.mark.asyncio
    async def test_compiler_retries_once_on_validation_failure(self):
        # First reply: cites a chunk_id that's NOT in the evidence pool
        # → validation fails.
        bad_first = json.dumps({
            "confidence": "low",
            "affected_services": ["svc-a"],
            "trigger_event": {"chunk_id": "GHOST", "service": "svc-a", "timestamp": "x", "log_line": "x"},
            "propagation_chain": [],
            "ruled_out_hypotheses": [{"hypothesis": "h", "why_ruled_out": "x"}],
            "assumptions": [],
            "gaps": ["g"],
            "incident_window": {},
            "root_cause": "x",
        })
        good_second = json.dumps({
            "confidence": "low",
            "affected_services": ["svc-a"],
            "trigger_event": {"chunk_id": "c0", "service": "svc-a", "timestamp": "x", "log_line": "x"},
            "propagation_chain": [],
            "ruled_out_hypotheses": [{"hypothesis": "h", "why_ruled_out": "x"}],
            "assumptions": [],
            "gaps": ["g"],
            "incident_window": {},
            "root_cause": "x",
        })
        llm = _make_llm(bad_first, good_second)

        result = await compile_answer(
            llm=llm,
            query="why",
            resolved_intent=_ResolvedIntent(),
            evidence=_evidence(1),
            tool_ledger=_ledger("search_logs"),
        )

        assert result.attempts == 2
        assert result.source == "llm"
        assert result.answer["trigger_event"]["chunk_id"] == "c0"

    @pytest.mark.asyncio
    async def test_compiler_returns_invalid_with_floor_after_two_failures(self):
        # Both replies cite ghost chunk → validation fails twice.
        bad = json.dumps({
            "confidence": "high",
            "affected_services": ["svc-a"],
            "trigger_event": {"chunk_id": "GHOST", "service": "x", "timestamp": "x", "log_line": "x"},
            "propagation_chain": [],
            "ruled_out_hypotheses": [{"hypothesis": "h", "why_ruled_out": "x"}],
            "assumptions": [],
            "gaps": ["g"],
            "incident_window": {},
            "root_cause": "x",
        })
        llm = _make_llm(bad, bad)

        result = await compile_answer(
            llm=llm,
            query="why",
            resolved_intent=_ResolvedIntent(),
            evidence=_evidence(1),
            tool_ledger=_ledger("search_logs"),
        )

        assert result.source == "llm_invalid"
        # Confidence forced to low after validation failures.
        assert result.answer["confidence"] == "low"
        # Gap message recorded.
        assert any("validation" in g.lower() for g in result.answer["gaps"])


# ─── Deterministic synth fallback ────────────────────────────────────────────


class TestDeterministicSynth:
    def test_synth_uses_services_seen_in_evidence(self):
        ans = synthesize_answer(
            query="why",
            resolved_intent=_ResolvedIntent(),
            evidence=_evidence(2),
            tool_ledger=_ledger("search_logs", "scan_window"),
        )
        assert set(ans["affected_services"]) == {"svc-a", "svc-b"}
        assert ans["confidence"] == "low"
        assert ans["incident_window"]["start"]
        assert ans["incident_window"]["end"]

    def test_synth_picks_earliest_error_as_trigger(self):
        ev = [
            {"chunk_id": "c0", "service": "x", "timestamp": "t", "level": "INFO", "message": "ok"},
            {"chunk_id": "c1", "service": "x", "timestamp": "t", "level": "ERROR", "message": "boom"},
        ]
        ans = synthesize_answer(query="q", resolved_intent=None, evidence=ev, tool_ledger={})
        assert ans["trigger_event"]["chunk_id"] == "c1"

    @pytest.mark.asyncio
    async def test_compiler_falls_to_synth_when_llm_raises(self):
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("provider down"))

        result = await compile_answer(
            llm=llm,
            query="why",
            resolved_intent=_ResolvedIntent(),
            evidence=_evidence(1),
            tool_ledger=_ledger("search_logs"),
        )

        assert result.source == "deterministic"
        assert result.answer["confidence"] == "low"
        # Synth populates affected_services from the evidence.
        assert result.answer["affected_services"] == ["svc-a"]


# ─── enforce_floors ──────────────────────────────────────────────────────────


class TestEnforceFloors:
    def test_high_with_few_citations_is_downgraded_to_medium(self):
        ans = {
            "confidence": "high",
            "affected_services": ["svc-a"],
            "trigger_event": {"chunk_id": "c0"},
            "propagation_chain": [],
            "gaps": [],
        }
        adjusted, notes = enforce_floors(ans, _evidence(1))
        # high -> medium because only 1 cited chunk_id (need >=2 for high).
        # The downgrade adds an explanatory gap so the empty-gaps check sees
        # gaps as non-empty afterward; final confidence is "medium".
        assert adjusted["confidence"] == "medium"
        assert any("citation" in n.lower() for n in notes)

    def test_low_with_empty_gaps_is_left_alone(self):
        ans = {
            "confidence": "low",
            "affected_services": ["svc-a"],
            "trigger_event": {"chunk_id": "c0"},
            "propagation_chain": [],
            "gaps": [],
        }
        adjusted, _ = enforce_floors(ans, _evidence(1))
        assert adjusted["confidence"] == "low"

    def test_affected_service_not_in_evidence_flagged(self):
        ans = {
            "confidence": "high",
            "affected_services": ["svc-a", "ghost-service"],
            "trigger_event": {"chunk_id": "c0"},
            "propagation_chain": [{"chunk_id": "c1", "service": "svc-b"}],
            "gaps": ["have gaps"],
        }
        adjusted, notes = enforce_floors(ans, _evidence(2))
        assert any("ghost-service" in n for n in notes)
        # High with 2 cited chunks stays high; affected mismatch downgrades by 1.
        assert adjusted["confidence"] == "medium"

    def test_invalid_confidence_string_coerced_to_low(self):
        ans = {
            "confidence": "VERY HIGH",
            "affected_services": [],
            "trigger_event": {},
            "propagation_chain": [],
            "gaps": [],
        }
        adjusted, notes = enforce_floors(ans, [])
        assert adjusted["confidence"] == "low"
        assert any("coerced" in n.lower() for n in notes)
