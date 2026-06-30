"""Tests for the loop-as-gatherer behaviors introduced in Issue #48:
- done_gathering signal exits the loop and triggers the compile call
- Legacy submit_answer is treated as a done_gathering signal
- Null-action turn re-prompts once without spending budget; exits on second
- Stall detection: 2 consecutive empty tool calls exits gathering early
- Separate reflection budget: reflections do not consume max_iterations
- InvestigationResult.stats carries the expected telemetry
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from repi.investigation.react_loop import ReactInvestigationLoop


# ─── Scaffolding ─────────────────────────────────────────────────────────────


def _action(i: int, tool: str = "search_logs", **args) -> str:
    args.setdefault("query", f"q{i}")
    return json.dumps({"thought": f"step {i}", "action": {"tool": tool, "args": args}})


def _done(reason: str = "ok") -> str:
    return json.dumps({"thought": "done", "action": {"tool": "done_gathering", "args": {"reason": reason}}})


def _legacy_submit() -> str:
    return json.dumps({
        "thought": "submitting",
        "action": {"tool": "submit_answer", "args": {"confidence": "high"}},
    })


def _thought_only() -> str:
    return json.dumps({"thought": "I'm just thinking, no tool call"})


def _compile() -> str:
    return json.dumps({
        "confidence": "low",
        "affected_services": ["svc-a"],
        "trigger_event": {},
        "propagation_chain": [],
        "ruled_out_hypotheses": [{"hypothesis": "x", "why_ruled_out": "y"}],
        "assumptions": [],
        "gaps": ["fixture"],
        "incident_window": {},
        "root_cause": "test",
    })


class _FakeInv:
    def __init__(self):
        self.id = uuid4()
        self.status = "started"
        self.pending_question = None
        self.total_llm_calls = 0
        self.current_step = 1


class _FakeChunk:
    def __init__(self, d: dict):
        self.chunk_id = d.get("chunk_id", "")
        self.service = d.get("service", "")
        self.timestamp = d.get("timestamp", "")
        self.message = d.get("message") or d.get("text", "")


class _FakeStore:
    def __init__(self):
        self.inv = _FakeInv()
        self.steps: list[dict] = []
        self.chunks: list[_FakeChunk] = []

    async def get_by_id(self, i): return self.inv
    async def get_or_create(self, q): return self.inv
    async def create(self, q): return self.inv
    async def get_steps(self, i): return []
    async def get_chunks(self, i): return list(self.chunks)
    async def add_step(self, **k): self.steps.append(k)
    async def add_chunks(self, i, c):
        self.chunks.extend(_FakeChunk(item) for item in c)
    async def increment_llm_calls(self, i): self.inv.total_llm_calls += 1
    async def finalize(self, i, a, status="completed"):
        self.inv.answer = a
        self.inv.status = status
    async def set_awaiting_clarification(self, i, q): pass


def _build_loop(responses, tool=None, *, max_iterations=8, enable_reflection=False,
                 min_gathering_actions=0):
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=list(responses))
    if tool is None:
        _i = {"n": 0}
        async def _default_tool(**_):
            _i["n"] += 1
            return [{"chunk_id": f"c{_i['n']}", "service": "svc-a", "text": "x"}]
        tool = _default_tool
    loop = ReactInvestigationLoop(
        llm=llm,
        tools={"search_logs": tool},
        known_services=["svc-a"],
        pool=None,
        store=_FakeStore(),
        max_iterations=max_iterations,
        min_gathering_actions=min_gathering_actions,
        min_iteration_delay=0,
        enable_reflection=enable_reflection,
    )
    loop._wait_for_rate_limit = AsyncMock(return_value=None)
    return loop


QUERY = "show errors in last 1 hour"


# ─── done_gathering ──────────────────────────────────────────────────────────


class TestDoneGathering:
    @pytest.mark.asyncio
    async def test_done_gathering_signal_triggers_compile(self):
        loop = _build_loop([_action(0), _done("test exit"), _compile()])

        result = await loop.investigate(QUERY, resume=False)

        kinds = [s.kind for s in result.steps]
        assert "signal" in kinds
        assert "compile" in kinds
        # Compile step is always last.
        assert result.steps[-1].kind == "compile"
        # Answer was populated by the compile call (not the empty stub).
        ans = json.loads(result.answer)
        assert ans["root_cause"] == "test"
        assert ans["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_legacy_submit_answer_treated_as_done_signal(self):
        loop = _build_loop([_action(0), _legacy_submit(), _compile()])

        result = await loop.investigate(QUERY, resume=False)

        # The legacy submit_answer call is recorded as a signal step (not a
        # finalize on its own), and the compiler still produces the answer.
        signal_steps = [s for s in result.steps if s.kind == "signal"]
        assert len(signal_steps) == 1
        # And the answer comes from the COMPILER, not the LLM's submit_answer args.
        ans = json.loads(result.answer)
        assert ans["root_cause"] == "test"


# ─── Null-action guard ───────────────────────────────────────────────────────


class TestNullActionGuard:
    @pytest.mark.asyncio
    async def test_thought_only_turn_reprompts_then_recovers(self):
        # Turn 0: thought only (no action). Re-prompt should fire.
        # Turn 1: real action.
        # Turn 2: done.
        # Turn 3: compile.
        loop = _build_loop([
            _thought_only(),
            _action(1),
            _done(),
            _compile(),
        ])

        result = await loop.investigate(QUERY, resume=False)

        # The thought-only turn did NOT advance the budget, but the action
        # that followed it DID get persisted. So we expect one action step.
        action_steps = [s for s in result.steps if s.kind is None and s.action]
        assert len(action_steps) == 1
        assert action_steps[0].action.tool_call.name == "search_logs"
        # And the loop completed normally with a compile step.
        assert result.steps[-1].kind == "compile"

    @pytest.mark.asyncio
    async def test_two_consecutive_thought_only_turns_force_exit(self):
        # Turn 0: thought only → re-prompt
        # Turn 1: thought only AGAIN → forced exit
        # Then compile call.
        loop = _build_loop([_thought_only(), _thought_only(), _compile()])

        result = await loop.investigate(QUERY, resume=False)

        # No action steps got persisted. Loop exited and compiler ran.
        action_steps = [s for s in result.steps if s.kind is None and s.action]
        assert len(action_steps) == 0
        assert result.steps[-1].kind == "compile"


# ─── Stall detection ─────────────────────────────────────────────────────────


class TestStallDetection:
    @pytest.mark.asyncio
    async def test_two_consecutive_empty_tool_calls_exit_gathering(self):
        # Tool always returns [] → every call is "empty".
        async def empty_tool(**_):
            return []

        loop = _build_loop(
            [_action(0), _action(1), _action(2), _action(3), _compile()],
            tool=empty_tool,
            max_iterations=12,
        )

        result = await loop.investigate(QUERY, resume=False)

        # Stall triggered after the 2nd empty call → only 2 action steps recorded.
        action_steps = [s for s in result.steps if s.kind is None and s.action]
        assert len(action_steps) == 2
        assert result.stats["gathering_exit_reason"] == "stalled_no_new_evidence"


# ─── Separate reflection budget ──────────────────────────────────────────────


class TestReflectionBudget:
    @pytest.mark.asyncio
    async def test_reflections_do_not_consume_action_budget(self):
        # max_iterations=4 ACTIONS; reflection_interval=2; max_reflections=2.
        # Without the separate-budget guarantee, 2 reflections would consume
        # 2 of the 4 iterations and we'd only see 2 actions. With it, we see
        # all 4 actions plus 1 reflection that fires between them.
        responses = [
            _action(0),
            _action(1),
            json.dumps({"thought": "reflection content #1"}),
            _action(2),
            _action(3),  # action #4; loop exits at the top of the next iter.
            _done(),
            _compile(),
        ]
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=list(responses))

        _i = {"n": 0}
        async def tool(**_):
            _i["n"] += 1
            return [{"chunk_id": f"c{_i['n']}", "service": "svc-a", "text": "x"}]

        loop = ReactInvestigationLoop(
            llm=llm, tools={"search_logs": tool}, known_services=["svc-a"],
            pool=None, store=_FakeStore(),
            max_iterations=4, min_gathering_actions=0, min_iteration_delay=0,
            enable_reflection=True, reflection_interval=2, max_reflections=2,
        )
        loop._wait_for_rate_limit = AsyncMock(return_value=None)

        result = await loop.investigate(QUERY, resume=False)

        action_steps = [s for s in result.steps if s.kind is None and s.action]
        reflections = [s for s in result.steps if s.kind == "reflection"]
        # Key property: 4 ACTION steps were budgeted, all 4 ran. Reflection
        # turn did NOT eat into that budget.
        assert len(action_steps) == 4
        assert len(reflections) >= 1

    @pytest.mark.asyncio
    async def test_reflections_capped_by_max_reflections(self):
        # max_reflections=1, reflection_interval=1 → only one reflection fires
        # even though the interval allows many.
        responses = [
            _action(0),
            json.dumps({"thought": "reflection 1"}),
            _action(1),
            _action(2),  # would normally trigger another reflection but cap is 1
            _done(),
            _compile(),
        ]
        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=list(responses))

        _i = {"n": 0}
        async def tool(**_):
            _i["n"] += 1
            return [{"chunk_id": f"c{_i['n']}", "service": "svc-a", "text": "x"}]

        loop = ReactInvestigationLoop(
            llm=llm, tools={"search_logs": tool}, known_services=["svc-a"],
            pool=None, store=_FakeStore(),
            max_iterations=6, min_gathering_actions=0, min_iteration_delay=0,
            enable_reflection=True, reflection_interval=1, max_reflections=1,
        )
        loop._wait_for_rate_limit = AsyncMock(return_value=None)

        result = await loop.investigate(QUERY, resume=False)

        reflections = [s for s in result.steps if s.kind == "reflection"]
        assert len(reflections) == 1
        assert result.stats["reflections_used"] == 1


# ─── Stats payload ────────────────────────────────────────────────────────────


class TestStatsPayload:
    @pytest.mark.asyncio
    async def test_stats_carries_telemetry(self):
        loop = _build_loop([_action(0), _action(1), _done("explicit"), _compile()])

        result = await loop.investigate(QUERY, resume=False)

        s = result.stats
        assert s["iterations_used"] == 2
        assert s["reflections_used"] == 0
        assert s["chunks_gathered"] >= 2
        assert "search_logs" in s["tools_called"]
        assert s["compile_source"] == "llm"
        assert s["gathering_exit_reason"] == "explicit"
