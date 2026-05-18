"""Tests for the reflection checkpoint mechanism (issue #10)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from repi.investigation.react_loop import (
    REFLECTION_PROMPT,
    ReactInvestigationLoop,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _action_response(step_idx: int) -> str:
    return json.dumps({
        "thought": f"investigating step {step_idx}",
        "action": {"tool": "search_logs", "args": {"query": f"q{step_idx}"}},
    })


def _reflection_response(step_idx: int) -> str:
    return json.dumps({
        "thought": f"reflection summary at step {step_idx}: hypotheses, evidence, next action, give-up decision",
    })


def _final_answer_response() -> str:
    return json.dumps({
        "thought": "done",
        "answer": {
            "confidence": "high",
            "affected_services": ["service-a"],
            "trigger_event": {},
            "propagation_chain": [],
            "ruled_out_hypotheses": [],
            "assumptions": [],
            "gaps": [],
            "incident_window": {},
            "root_cause": "test",
        },
    })


class _FakeInvestigation:
    def __init__(self):
        self.id = uuid4()
        self.status = "started"
        self.pending_question = None
        self.total_llm_calls = 0
        self.current_step = 1


class _FakeStore:
    """In-memory stand-in for InvestigationStore. Records add_step calls so tests
    can assert on the persisted kind/action/observation shape."""

    def __init__(self):
        self.inv = _FakeInvestigation()
        self.steps: list[dict] = []   # captured add_step kwargs
        self.chunks: list[dict] = []

    async def get_by_id(self, inv_id):
        return self.inv

    async def get_or_create(self, query):
        return self.inv

    async def create(self, query):
        return self.inv

    async def get_steps(self, inv_id):
        return []

    async def get_chunks(self, inv_id):
        return []

    async def add_step(self, investigation_id, step_number, thought, action=None, observation=None, kind=None):
        self.steps.append({
            "step_number": step_number,
            "thought": thought,
            "action": action,
            "observation": observation,
            "kind": kind,
        })
        return None

    async def add_chunks(self, inv_id, chunks):
        return None

    async def increment_llm_calls(self, inv_id):
        self.inv.total_llm_calls += 1

    async def finalize(self, inv_id, answer, status="completed"):
        self.inv.answer = answer
        self.inv.status = status

    async def set_awaiting_clarification(self, inv_id, question):
        self.inv.status = "awaiting_clarification"
        self.inv.pending_question = question


def _build_loop(llm_responses, *, enable_reflection=True, reflection_interval=3, max_iterations=12):
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=list(llm_responses))

    tools = {"search_logs": AsyncMock(return_value=[])}

    loop = ReactInvestigationLoop(
        llm=llm,
        tools=tools,
        known_services=["service-a", "service-b"],
        pool=None,
        store=_FakeStore(),
        max_iterations=max_iterations,
        min_iteration_delay=0,
        enable_reflection=enable_reflection,
        reflection_interval=reflection_interval,
    )
    # Disable per-call rate limit pacing for tests.
    loop._wait_for_rate_limit = AsyncMock(return_value=None)
    return loop


QUERY_WITH_TIME_AND_SYMPTOM = "show errors in last 1 hour"


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestReflectionInjection:
    @pytest.mark.asyncio
    async def test_reflection_injected_every_n_steps(self):
        """With N=3, the loop should produce kind sequence:
        action, action, action, reflection, action, action, action, reflection, action, final"""
        responses = [
            _action_response(0),
            _action_response(1),
            _action_response(2),
            _reflection_response(3),
            _action_response(4),
            _action_response(5),
            _action_response(6),
            _reflection_response(7),
            _action_response(8),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, reflection_interval=3, max_iterations=12)

        result = await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        kinds = [s.kind for s in result.steps]
        # 3 actions, then reflection (kind="reflection")
        assert kinds[0:3] == [None, None, None]
        assert kinds[3] == "reflection"
        # next 3 actions, then second reflection
        assert kinds[4:7] == [None, None, None]
        assert kinds[7] == "reflection"
        # final action runs, then final_answer breaks the loop (no step appended for the answer)
        assert kinds[8] is None

        reflection_count = sum(1 for k in kinds if k == "reflection")
        assert reflection_count == 2

    @pytest.mark.asyncio
    async def test_no_reflection_when_disabled(self):
        """With enable_reflection=False, no reflection steps are produced even after N actions."""
        responses = [
            _action_response(0),
            _action_response(1),
            _action_response(2),
            _action_response(3),
            _action_response(4),
            _action_response(5),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, enable_reflection=False, reflection_interval=3, max_iterations=10)

        result = await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        kinds = [s.kind for s in result.steps]
        assert all(k is None for k in kinds), f"expected zero reflections, got kinds={kinds}"
        # Loop was not pre-empted by any reflection turn.
        assert loop.llm.complete.await_count == len(responses)

    @pytest.mark.asyncio
    async def test_reflection_step_has_action_none_and_correct_kind(self):
        """Reflection step persisted via store has action=None, observation=None, kind='reflection'."""
        responses = [
            _action_response(0),
            _action_response(1),
            _reflection_response(2),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, reflection_interval=2, max_iterations=6)

        await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        captured = loop.store.steps
        reflection_records = [s for s in captured if s["kind"] == "reflection"]
        assert len(reflection_records) == 1
        r = reflection_records[0]
        assert r["action"] is None
        assert r["observation"] is None
        assert r["kind"] == "reflection"
        assert "reflection summary" in r["thought"]

    @pytest.mark.asyncio
    async def test_reflection_failure_rolls_back_dangling_prompt(self):
        """If the reflection LLM call raises, the appended REFLECTION_PROMPT
        must NOT be left in the message history — otherwise the next iteration
        sees an unanswered user turn and gets confused."""

        # 3 actions push us to reflection threshold; the reflection call itself
        # raises; iteration continues and the next action runs cleanly.
        action_iter = iter([
            _action_response(0),
            _action_response(1),
            _action_response(2),
            _action_response(4),  # post-failure recovery action
        ])
        state = {"raised": False}

        def _side_effect(messages):
            last_user = next((m for m in reversed(messages) if m.role == "user"), None)
            if last_user is not None and last_user.content == REFLECTION_PROMPT and not state["raised"]:
                state["raised"] = True
                raise RuntimeError("upstream LLM rate-limited mid-reflection")
            try:
                return next(action_iter)
            except StopIteration:
                return _final_answer_response()

        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=_side_effect)

        loop = ReactInvestigationLoop(
            llm=llm,
            tools={"search_logs": AsyncMock(return_value=[])},
            known_services=["service-a"],
            pool=None,
            store=_FakeStore(),
            max_iterations=12,
            min_iteration_delay=0,
            enable_reflection=True,
            reflection_interval=3,
        )
        loop._wait_for_rate_limit = AsyncMock(return_value=None)

        await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        # On the next LLM call after the reflection failure, the prompt must
        # NOT be the dangling REFLECTION_PROMPT.
        call_after_failure = llm.complete.call_args_list[4]  # 3 actions + 1 reflection-that-raised + this one
        messages = call_after_failure.args[0]
        last_user = next(m for m in reversed(messages) if m.role == "user")
        assert last_user.content != REFLECTION_PROMPT, (
            "REFLECTION_PROMPT was left dangling after the failed reflection call"
        )

    @pytest.mark.asyncio
    async def test_reflection_prompt_appended_before_call(self):
        """When reflection fires, the REFLECTION_PROMPT must be the last user message before the LLM call."""
        responses = [
            _action_response(0),
            _action_response(1),
            _action_response(2),
            _reflection_response(3),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, reflection_interval=3, max_iterations=8)

        await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        # The 4th LLM call is the reflection one — inspect what was passed.
        reflection_call = loop.llm.complete.call_args_list[3]
        messages = reflection_call.args[0]
        last_user = next(m for m in reversed(messages) if m.role == "user")
        assert last_user.content == REFLECTION_PROMPT
