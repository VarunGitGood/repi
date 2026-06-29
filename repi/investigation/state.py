from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable, Optional
from uuid import UUID

import asyncpg

from repi.llm.provider import LLMProvider, Message
from repi.investigation.store import InvestigationStore
from repi.investigation.tools import ToolCall, ToolResult
from repi.intent.resolver import ResolvedIntent


class Phase(str, Enum):
    RESOLVING = "resolving"
    SWEEPING = "sweeping"
    GATHERING = "gathering"
    REFLECTING = "reflecting"
    COMPILING = "compiling"
    WAITING_CLARIFICATION = "waiting_clarification"
    DONE = "done"


@dataclass
class Thought:
    content: str


@dataclass
class Action:
    tool_call: ToolCall


@dataclass
class Observation:
    tool_result: ToolResult


@dataclass
class InvestigationStep:
    step_number: int
    thought: Thought
    action: Optional[Action] = None
    observation: Optional[Observation] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    kind: Optional[str] = None


@dataclass
class InvestigationResult:
    id: str
    query: str
    steps: list[InvestigationStep]
    answer: str
    evidence_chunk_ids: list[str]
    confidence: str
    duration_seconds: float
    evidence: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass
class InvestigationState:
    phase: Phase
    investigation_id: UUID
    query: str
    messages: list[Message]
    tool_call_ledger: dict[str, dict]
    actions_taken: int = 0
    reflections_used: int = 0
    action_steps_since_reflection: int = 0
    consecutive_empty_tool_calls: int = 0
    processed_steps: list[InvestigationStep] = field(default_factory=list)
    evidence_chunk_ids: set[str] = field(default_factory=set)
    resolved_intent: ResolvedIntent | None = None
    gathering_exit_reason: str = "max_actions_reached"
    pending_question: str | None = None
    next_step_number: int = 1
    null_action_reprompted: bool = False
    post_clarification: bool = False

    def to_json(self) -> str:
        return json.dumps(self._to_dict(), default=str)

    def _to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "investigation_id": str(self.investigation_id),
            "query": self.query,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "tool_call_ledger": self.tool_call_ledger,
            "actions_taken": self.actions_taken,
            "reflections_used": self.reflections_used,
            "action_steps_since_reflection": self.action_steps_since_reflection,
            "consecutive_empty_tool_calls": self.consecutive_empty_tool_calls,
            "evidence_chunk_ids": sorted(self.evidence_chunk_ids),
            "resolved_intent": _intent_to_dict(self.resolved_intent) if self.resolved_intent else None,
            "gathering_exit_reason": self.gathering_exit_reason,
            "pending_question": self.pending_question,
            "next_step_number": self.next_step_number,
            "null_action_reprompted": self.null_action_reprompted,
            "post_clarification": self.post_clarification,
        }

    @classmethod
    def from_json(cls, raw: str) -> InvestigationState:
        d = json.loads(raw)
        return cls(
            phase=Phase(d["phase"]),
            investigation_id=UUID(d["investigation_id"]),
            query=d["query"],
            messages=[Message(role=m["role"], content=m["content"]) for m in d["messages"]],
            tool_call_ledger=d.get("tool_call_ledger", {}),
            actions_taken=d.get("actions_taken", 0),
            reflections_used=d.get("reflections_used", 0),
            action_steps_since_reflection=d.get("action_steps_since_reflection", 0),
            consecutive_empty_tool_calls=d.get("consecutive_empty_tool_calls", 0),
            evidence_chunk_ids=set(d.get("evidence_chunk_ids", [])),
            resolved_intent=_intent_from_dict(d["resolved_intent"]) if d.get("resolved_intent") else None,
            gathering_exit_reason=d.get("gathering_exit_reason", "max_actions_reached"),
            pending_question=d.get("pending_question"),
            next_step_number=d.get("next_step_number", 1),
            null_action_reprompted=d.get("null_action_reprompted", False),
            post_clarification=d.get("post_clarification", False),
        )


@dataclass
class LoopDeps:
    llm: LLMProvider
    tools: dict[str, Callable]
    known_services: list[str]
    pool: asyncpg.Pool | None
    store: InvestigationStore | None
    max_iterations: int = 10
    min_iteration_delay: float = 2.0
    enable_reflection: bool = True
    reflection_interval: int = 3
    max_reflections: int = 2
    llm_max_calls_per_min: int = 60
    on_step: Callable[[InvestigationStep], Awaitable[None]] | None = None
    on_phase_change: Callable[[str], Awaitable[None]] | None = None
    llm_call_timestamps: list[float] = field(default_factory=list)


def _intent_to_dict(intent: ResolvedIntent) -> dict:
    return {
        "time_from": intent.time_from.isoformat() if intent.time_from else None,
        "time_to": intent.time_to.isoformat() if intent.time_to else None,
        "services": intent.services,
        "symptoms": intent.symptoms,
        "entities": intent.entities,
        "assumed": intent.assumed,
    }


def _intent_from_dict(d: dict) -> ResolvedIntent:
    return ResolvedIntent(
        time_from=datetime.fromisoformat(d["time_from"]) if d.get("time_from") else None,
        time_to=datetime.fromisoformat(d["time_to"]) if d.get("time_to") else None,
        services=d.get("services", []),
        symptoms=d.get("symptoms", []),
        entities=d.get("entities", []),
        assumed=d.get("assumed", []),
    )
