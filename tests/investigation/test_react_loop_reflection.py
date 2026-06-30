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


def _done_signal_response() -> str:
    return json.dumps({
        "thought": "done gathering",
        "action": {"tool": "done_gathering", "args": {"reason": "test_complete"}},
    })


def _compile_response() -> str:
    return json.dumps({
        "confidence": "low",
        "affected_services": ["service-a"],
        "trigger_event": {},
        "propagation_chain": [],
        "ruled_out_hypotheses": [
            {"hypothesis": "service-b", "why_ruled_out": "no errors in this window"},
        ],
        "assumptions": [],
        "gaps": ["test fixture: no real evidence"],
        "incident_window": {},
        "root_cause": "test",
    })


# Legacy name kept so the test bodies read cleanly. Now resolves to the
# gathering-exit signal; tests that need the compile call append _compile_response()
# explicitly.
def _final_answer_response() -> str:
    return _done_signal_response()


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


def _build_loop(
    llm_responses, *, enable_reflection=True, reflection_interval=3,
    max_iterations=12, max_reflections=2,
):
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=list(llm_responses))

    # Tool returns a fresh chunk per call so stall detection (2 consecutive
    # empty tool calls -> early exit) does NOT fire during reflection tests.
    _counter = {"i": 0}

    async def _fake_tool(**_kwargs):
        _counter["i"] += 1
        return [{"chunk_id": f"c{_counter['i']}", "service": "service-a", "text": "x"}]

    tools = {"search_logs": _fake_tool}

    loop = ReactInvestigationLoop(
        llm=llm,
        tools=tools,
        known_services=["service-a", "service-b"],
        pool=None,
        store=_FakeStore(),
        max_iterations=max_iterations,
        min_gathering_actions=0,
        min_iteration_delay=0,
        enable_reflection=enable_reflection,
        reflection_interval=reflection_interval,
        max_reflections=max_reflections,
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
            _compile_response(),
        ]
        loop = _build_loop(
            responses, reflection_interval=3, max_iterations=12, max_reflections=5,
        )

        result = await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        kinds = [s.kind for s in result.steps]
        # 3 actions, then reflection (kind="reflection")
        assert kinds[0:3] == [None, None, None]
        assert kinds[3] == "reflection"
        # next 3 actions, then second reflection
        assert kinds[4:7] == [None, None, None]
        assert kinds[7] == "reflection"
        # final action runs, then done_gathering signal (kind="signal"), then compile step.
        assert kinds[8] is None
        assert kinds[9] == "signal"
        assert kinds[10] == "compile"

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
            _compile_response(),
        ]
        loop = _build_loop(responses, enable_reflection=False, reflection_interval=3, max_iterations=10)

        result = await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        kinds = [s.kind for s in result.steps]
        # No "reflection" entries; mix of gathering (None), "signal", and "compile".
        assert "reflection" not in kinds, f"expected zero reflections, got kinds={kinds}"
        # Loop was not pre-empted by any reflection turn — all responses consumed.
        assert loop.llm.complete.await_count == len(responses)

    @pytest.mark.asyncio
    async def test_reflection_step_has_action_none_and_correct_kind(self):
        """Reflection step persisted via store has action=None, observation=None, kind='reflection'."""
        responses = [
            _action_response(0),
            _action_response(1),
            _reflection_response(2),
            _final_answer_response(),
            _compile_response(),
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

        # Capture a deep snapshot of `messages` on each LLM call so we can
        # inspect the state at call time (the loop mutates messages across
        # iterations).
        import copy

        action_iter = iter([
            _action_response(0),
            _action_response(1),
            _action_response(2),
            _action_response(4),  # post-failure recovery action
            _final_answer_response(),
            _compile_response(),
        ])
        state = {"reflection_failures": 0}
        snapshots: list[list] = []

        async def _side_effect(messages, **_kwargs):
            snapshots.append(copy.deepcopy(messages))
            last_user = next((m for m in reversed(messages) if m.role == "user"), None)
            if last_user is not None and last_user.content == REFLECTION_PROMPT and state["reflection_failures"] < 3:
                state["reflection_failures"] += 1
                raise RuntimeError("upstream LLM rate-limited mid-reflection")
            try:
                return next(action_iter)
            except StopIteration:
                return _final_answer_response()

        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=_side_effect)

        # Tool returns a fresh chunk per call so stall detection doesn't fire.
        _i = {"n": 0}
        async def _tool(**_):
            _i["n"] += 1
            return [{"chunk_id": f"c{_i['n']}", "service": "service-a", "text": "x"}]

        loop = ReactInvestigationLoop(
            llm=llm,
            tools={"search_logs": _tool},
            known_services=["service-a"],
            pool=None,
            store=_FakeStore(),
            max_iterations=12,
            min_gathering_actions=0,
            min_iteration_delay=0,
            enable_reflection=True,
            reflection_interval=3,
            max_reflections=2,
        )
        loop._wait_for_rate_limit = AsyncMock(return_value=None)

        await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        # Snapshot after the failure: 3 action calls + 3 reflection retries = 6
        # snapshots so far; the next call (index 6) is the recovery LLM call.
        call_after_failure = snapshots[6]
        last_user = next(m for m in reversed(call_after_failure) if m.role == "user")
        assert last_user.content != REFLECTION_PROMPT, (
            "REFLECTION_PROMPT was left dangling after the failed reflection call"
        )

    @pytest.mark.asyncio
    async def test_reflection_prompt_appended_before_call(self):
        """When reflection fires, the REFLECTION_PROMPT must be the last user message before the LLM call."""
        # AsyncMock.call_args_list captures the messages list by reference;
        # the loop mutates that list across iterations, so we deepcopy on
        # every call to preserve the state AT call time.
        import copy
        snapshots: list[list] = []

        async def _capture(messages, **kwargs):
            snapshots.append(copy.deepcopy(messages))
            return next(_iter)

        responses = iter([
            _action_response(0),
            _action_response(1),
            _action_response(2),
            _reflection_response(3),
            _final_answer_response(),
            _compile_response(),
        ])
        _iter = responses

        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=_capture)
        loop = ReactInvestigationLoop(
            llm=llm,
            tools={"search_logs": _build_loop.__wrapped__ if hasattr(_build_loop, "__wrapped__") else None},  # placeholder
            known_services=["service-a"],
            pool=None,
            store=_FakeStore(),
            max_iterations=8,
            min_gathering_actions=0,
            min_iteration_delay=0,
            enable_reflection=True,
            reflection_interval=3,
            max_reflections=2,
        )
        # Override with a chunk-returning tool so stall detection doesn't fire.
        _i = {"n": 0}
        async def _tool(**_):
            _i["n"] += 1
            return [{"chunk_id": f"c{_i['n']}", "service": "service-a", "text": "x"}]
        loop.tools = {"search_logs": _tool}
        loop._wait_for_rate_limit = AsyncMock(return_value=None)

        await loop.investigate(QUERY_WITH_TIME_AND_SYMPTOM, resume=False)

        # The 4th LLM call (index 3) is the reflection one.
        reflection_snapshot = snapshots[3]
        last_user = next(m for m in reversed(reflection_snapshot) if m.role == "user")
        assert last_user.content == REFLECTION_PROMPT
