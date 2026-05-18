"""Tests for the tool-call ledger / repeat-call dedupe (issue #11)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from repi.investigation.react_loop import ReactInvestigationLoop


# ─── Shared scaffolding ──────────────────────────────────────────────────────

def _action_response(tool: str, args: dict) -> str:
    return json.dumps({"thought": f"calling {tool}", "action": {"tool": tool, "args": args}})


def _final_answer_response() -> str:
    return json.dumps({
        "thought": "done",
        "answer": {
            "confidence": "high",
            "affected_services": ["svc"],
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
    def __init__(self):
        self.inv = _FakeInvestigation()
        self.steps: list[dict] = []

    async def get_by_id(self, inv_id): return self.inv
    async def get_or_create(self, query): return self.inv
    async def create(self, query): return self.inv
    async def get_steps(self, inv_id): return []
    async def get_chunks(self, inv_id): return []
    async def add_step(self, **kwargs):
        self.steps.append(kwargs)
    async def add_chunks(self, inv_id, chunks): return None
    async def increment_llm_calls(self, inv_id): self.inv.total_llm_calls += 1
    async def finalize(self, inv_id, answer, status="completed"):
        self.inv.answer = answer
        self.inv.status = status
    async def set_awaiting_clarification(self, inv_id, q): pass


def _build_loop(llm_responses, *, tool: AsyncMock, enable_reflection=False):
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=list(llm_responses))

    loop = ReactInvestigationLoop(
        llm=llm,
        tools={"search_logs": tool},
        known_services=["svc"],
        pool=None,
        store=_FakeStore(),
        max_iterations=12,
        min_iteration_delay=0,
        enable_reflection=enable_reflection,
    )
    loop._wait_for_rate_limit = AsyncMock(return_value=None)
    return loop


QUERY = "show errors in last 1 hour"


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestLedgerDedupe:
    @pytest.mark.asyncio
    async def test_repeat_call_short_circuits_tool_invocation(self):
        """Identical (tool, args) on a second call must NOT invoke the underlying tool."""
        tool = AsyncMock(return_value=[{"chunk_id": "c1", "service": "svc", "text": "boom"}])
        responses = [
            _action_response("search_logs", {"query": "timeout", "service": "svc"}),
            _action_response("search_logs", {"query": "timeout", "service": "svc"}),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, tool=tool)

        await loop.investigate(QUERY, resume=False)

        # The tool fn was awaited only once even though the LLM asked for it twice.
        assert tool.await_count == 1

    @pytest.mark.asyncio
    async def test_normalized_args_treated_as_repeat(self):
        """Same args in a different key order should still hash to the same ledger entry."""
        tool = AsyncMock(return_value=[])
        responses = [
            _action_response("search_logs", {"query": "x", "service": "svc"}),
            _action_response("search_logs", {"service": "svc", "query": "x"}),  # reordered
            _final_answer_response(),
        ]
        loop = _build_loop(responses, tool=tool)

        await loop.investigate(QUERY, resume=False)

        assert tool.await_count == 1, "reordered keys should still dedupe"

    @pytest.mark.asyncio
    async def test_repeat_call_observation_is_marked(self):
        """When a repeat fires, the user-facing observation message must carry a note."""
        tool = AsyncMock(return_value=[{"chunk_id": "c1"}])
        responses = [
            _action_response("search_logs", {"q": "a"}),
            _action_response("search_logs", {"q": "a"}),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, tool=tool)

        await loop.investigate(QUERY, resume=False)

        # The third LLM call is the final-answer one. The user message right
        # before it must be the repeat-marked observation.
        third_call_messages = loop.llm.complete.call_args_list[2].args[0]
        last_user = next(m for m in reversed(third_call_messages) if m.role == "user")
        assert "repeat call" in last_user.content.lower()

    @pytest.mark.asyncio
    async def test_ledger_summary_injected_into_system_prompt(self):
        """After a tool call lands in the ledger, the system message on the next
        turn carries a 'TOOLS ALREADY CALLED' block summarizing what's been tried."""
        tool = AsyncMock(return_value=[])
        responses = [
            _action_response("search_logs", {"q": "foo"}),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, tool=tool)

        await loop.investigate(QUERY, resume=False)

        # Second LLM call sees the updated system message.
        second_call_messages = loop.llm.complete.call_args_list[1].args[0]
        system_msg = next(m for m in second_call_messages if m.role == "system")
        assert "TOOLS ALREADY CALLED" in system_msg.content
        assert "search_logs" in system_msg.content

    @pytest.mark.asyncio
    async def test_distinct_args_do_not_dedupe(self):
        """Different args should produce two real tool invocations."""
        tool = AsyncMock(return_value=[])
        responses = [
            _action_response("search_logs", {"q": "a"}),
            _action_response("search_logs", {"q": "b"}),
            _final_answer_response(),
        ]
        loop = _build_loop(responses, tool=tool)

        await loop.investigate(QUERY, resume=False)

        assert tool.await_count == 2
