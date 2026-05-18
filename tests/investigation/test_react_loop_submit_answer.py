"""Tests for the unified submit_answer convention (issue #15).

The ReAct loop accepts ONE canonical finalize convention: the LLM calls the
`submit_answer` tool with the answer dict as `args`. Legacy aliases
(`Final Answer`, `FinalAnswer`, `submit`, `finish`) still work for one release
but emit a warning. The undocumented top-level `"answer"` fallback also still
finalizes — it's a safety net for malformed LLM output.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from repi.investigation.react_loop import (
    FINAL_ANSWER_TOOL,
    ReactInvestigationLoop,
    _LEGACY_FINAL_ANSWER_ALIASES,
)


# ─── Scaffolding ─────────────────────────────────────────────────────────────

_ANSWER_PAYLOAD = {
    "confidence": "high",
    "affected_services": ["service-a"],
    "trigger_event": {},
    "propagation_chain": [],
    "ruled_out_hypotheses": [],
    "assumptions": [],
    "gaps": [],
    "incident_window": {},
    "root_cause": "test",
}


def _submit_tool_response(tool_name: str = FINAL_ANSWER_TOOL) -> str:
    return json.dumps({
        "thought": "ready to finalize",
        "action": {"tool": tool_name, "args": _ANSWER_PAYLOAD},
    })


def _top_level_answer_response() -> str:
    """Legacy / safety-net shape: thought + answer at the top level, no action."""
    return json.dumps({"thought": "done", "answer": _ANSWER_PAYLOAD})


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
        self.finalized: dict | None = None

    async def get_by_id(self, inv_id): return self.inv
    async def get_or_create(self, query): return self.inv
    async def create(self, query): return self.inv
    async def get_steps(self, inv_id): return []
    async def get_chunks(self, inv_id): return []
    async def add_step(self, **kwargs): self.steps.append(kwargs)
    async def add_chunks(self, inv_id, chunks): return None
    async def increment_llm_calls(self, inv_id): self.inv.total_llm_calls += 1
    async def finalize(self, inv_id, answer, status="completed"):
        self.finalized = {"answer": answer, "status": status}
        self.inv.answer = answer
        self.inv.status = status
    async def set_awaiting_clarification(self, inv_id, q): pass


def _build_loop(responses):
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=list(responses))
    loop = ReactInvestigationLoop(
        llm=llm,
        tools={"search_logs": AsyncMock(return_value=[])},
        known_services=["service-a"],
        pool=None,
        store=_FakeStore(),
        max_iterations=6,
        min_iteration_delay=0,
        enable_reflection=False,
    )
    loop._wait_for_rate_limit = AsyncMock(return_value=None)
    return loop


QUERY = "show errors in last 1 hour"


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestSubmitAnswerUnified:
    @pytest.mark.asyncio
    async def test_canonical_submit_answer_tool_finalizes(self):
        """The canonical convention — `tool=submit_answer` — must finalize the run."""
        loop = _build_loop([_submit_tool_response()])
        result = await loop.investigate(QUERY, resume=False)

        # Loop terminated cleanly with the answer stored.
        assert loop.store.finalized is not None
        finalized = json.loads(loop.store.finalized["answer"])
        assert finalized["root_cause"] == "test"
        # And the InvestigationResult carries the same.
        assert "test" in result.answer

    @pytest.mark.asyncio
    async def test_top_level_answer_shape_still_finalizes(self):
        """The undocumented safety-net shape — top-level "answer" key, no action —
        still works. Removing it would risk losing valid LLM output we already
        handle today."""
        loop = _build_loop([_top_level_answer_response()])
        await loop.investigate(QUERY, resume=False)

        assert loop.store.finalized is not None
        finalized = json.loads(loop.store.finalized["answer"])
        assert finalized["root_cause"] == "test"

    @pytest.mark.parametrize("legacy_alias", sorted(_LEGACY_FINAL_ANSWER_ALIASES))
    @pytest.mark.asyncio
    async def test_legacy_alias_still_finalizes_with_warning(self, legacy_alias, caplog):
        """Each pre-existing alias remains accepted for one release and emits a
        deprecation warning so we can detect when the LLM has stopped using it."""
        loop = _build_loop([_submit_tool_response(legacy_alias)])
        with caplog.at_level(logging.WARNING, logger="repi.investigation.react_loop"):
            await loop.investigate(QUERY, resume=False)

        # Finalized correctly.
        assert loop.store.finalized is not None
        # Warning naming the alias was emitted exactly once.
        warnings = [r for r in caplog.records if "Legacy final-answer alias" in r.message]
        assert len(warnings) == 1
        assert legacy_alias in warnings[0].message

    @pytest.mark.asyncio
    async def test_system_prompt_teaches_only_submit_answer(self):
        """The system prompt must mention submit_answer as the finalize path and
        NOT teach the old 'Final Answer:' format."""
        loop = _build_loop([_submit_tool_response()])
        prompt = loop._build_system_prompt()

        assert "submit_answer" in prompt
        # The old "Final Answer:" finalize prefix is gone from the FORMAT block.
        # (Still allowed in free text — e.g. CRITICAL RULES — but not as a
        # documented finalize convention.)
        assert "Final Answer: {" not in prompt
        # And the "Tool Call:" prefix from the old dual-format is gone too.
        assert "Tool Call: {" not in prompt
