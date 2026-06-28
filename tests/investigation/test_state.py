"""Tests for InvestigationState serialization and Phase transitions."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from repi.investigation.state import (
    Phase,
    InvestigationState,
    InvestigationStep,
    Thought,
)
from repi.intent.resolver import ResolvedIntent
from repi.llm.provider import Message
from repi.investigation.react_loop import HANDLERS


class TestStateSerializationRoundTrip:
    def test_minimal_state_round_trips(self):
        state = InvestigationState(
            phase=Phase.GATHERING,
            investigation_id=uuid4(),
            query="show errors",
            messages=[Message(role="user", content="show errors")],
            tool_call_ledger={},
        )
        restored = InvestigationState.from_json(state.to_json())

        assert restored.phase == state.phase
        assert restored.investigation_id == state.investigation_id
        assert restored.query == state.query
        assert len(restored.messages) == 1
        assert restored.messages[0].role == "user"
        assert restored.messages[0].content == "show errors"

    def test_full_state_round_trips(self):
        inv_id = uuid4()
        state = InvestigationState(
            phase=Phase.REFLECTING,
            investigation_id=inv_id,
            query="why did auth fail",
            messages=[
                Message(role="system", content="sys"),
                Message(role="user", content="q"),
                Message(role="assistant", content="a"),
            ],
            tool_call_ledger={
                "search_logs::{\"query\": \"auth\"}": {
                    "tool_name": "search_logs",
                    "args": {"query": "auth"},
                    "result": [{"chunk_id": "c1"}],
                }
            },
            actions_taken=3,
            reflections_used=1,
            action_steps_since_reflection=2,
            consecutive_empty_tool_calls=0,
            evidence_chunk_ids={"c1", "c2"},
            resolved_intent=ResolvedIntent(
                time_from=None,
                time_to=None,
                services=["auth-svc"],
                symptoms=["timeout"],
                entities=["abc-123"],
                assumed=["no time given"],
            ),
            gathering_exit_reason="max_actions_reached",
            pending_question=None,
            next_step_number=5,
            null_action_reprompted=True,
            post_clarification=False,
        )

        restored = InvestigationState.from_json(state.to_json())

        assert restored.phase == Phase.REFLECTING
        assert restored.investigation_id == inv_id
        assert restored.actions_taken == 3
        assert restored.reflections_used == 1
        assert restored.action_steps_since_reflection == 2
        assert restored.evidence_chunk_ids == {"c1", "c2"}
        assert restored.resolved_intent.services == ["auth-svc"]
        assert restored.resolved_intent.entities == ["abc-123"]
        assert restored.next_step_number == 5
        assert restored.null_action_reprompted is True
        assert len(restored.messages) == 3
        assert len(restored.tool_call_ledger) == 1

    def test_waiting_clarification_round_trips(self):
        state = InvestigationState(
            phase=Phase.WAITING_CLARIFICATION,
            investigation_id=uuid4(),
            query="show errors",
            messages=[],
            tool_call_ledger={},
            pending_question="Which service?",
        )
        restored = InvestigationState.from_json(state.to_json())

        assert restored.phase == Phase.WAITING_CLARIFICATION
        assert restored.pending_question == "Which service?"

    def test_resolved_intent_with_timestamps_round_trips(self):
        from datetime import datetime
        state = InvestigationState(
            phase=Phase.SWEEPING,
            investigation_id=uuid4(),
            query="errors last hour",
            messages=[],
            tool_call_ledger={},
            resolved_intent=ResolvedIntent(
                time_from=datetime(2026, 6, 29, 10, 0, 0),
                time_to=datetime(2026, 6, 29, 11, 0, 0),
                services=["api"],
            ),
        )
        restored = InvestigationState.from_json(state.to_json())

        assert restored.resolved_intent.time_from.year == 2026
        assert restored.resolved_intent.time_to.hour == 11


class TestTransitionTable:
    """Every phase in the dispatch table has a handler registered."""

    def test_all_non_terminal_phases_have_handlers(self):
        for phase in Phase:
            if phase == Phase.DONE:
                assert phase not in HANDLERS
            else:
                assert phase in HANDLERS, f"Missing handler for {phase}"

    def test_handler_count_matches_non_terminal_phases(self):
        non_terminal = [p for p in Phase if p != Phase.DONE]
        assert len(HANDLERS) == len(non_terminal)
