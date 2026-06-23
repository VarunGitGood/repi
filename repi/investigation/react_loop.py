from __future__ import annotations
import json
import logging
import asyncio
import time
import re
from datetime import datetime, timedelta
from uuid import UUID
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

import asyncpg

from repi.core.dates import DateHandler, default_date_handler as _dh
from repi.llm.adapters import LLMRateLimitError, LLMBadRequestError
from repi.llm.provider import LLMProvider, Message
from repi.investigation.tools import ToolCall, ToolResult, TOOL_SCHEMAS
from repi.retrieval.heuristics import cluster_logs
from repi.investigation.store import InvestigationStore
from repi.intent.resolver import resolve as resolve_intent, ResolvedIntent, ClarificationNeeded
from repi.investigation.sweep import auto_sweep
from repi.investigation.schema import InvestigationAnswer, validate_answer
from repi.investigation.compiler import compile_answer, synthesize_answer, CompileResult

logger = logging.getLogger(__name__)


# The ReAct loop only gathers evidence. The final InvestigationAnswer is
# produced by `repi.investigation.compiler` via a separate LLM call.
#
# `DONE_GATHERING_TOOL` is the LLM's voluntary exit signal for the gathering
# phase. Dispatcher-only — not in `TOOL_SCHEMAS`. Args: optional {"reason": "..."}.
#
# `LEGACY_SUBMIT_TOOL` is also accepted: if a model emits `submit_answer`, it
# is treated as a done-gathering signal (its args are discarded; the compiler
# produces the real answer).
DONE_GATHERING_TOOL = "done_gathering"
LEGACY_SUBMIT_TOOL = "submit_answer"


# Reflection turn injected every N action steps: the LLM steps back,
# summarises hypotheses + evidence, and picks the highest-value next action.
# Pure thought — no tool call on this turn. Termination is gated: only call
# `done_gathering` after multiple distinct lines of inquiry have all returned
# no useful evidence.
REFLECTION_PROMPT = (
    "Stop. Before your next action, reflect:\n"
    "1. What hypotheses have you considered so far?\n"
    "2. What evidence supports or refutes each hypothesis?\n"
    "3. What is the single highest-value next gathering action — and why?\n"
    "4. Termination check: if you have pursued multiple distinct lines of\n"
    "   inquiry and each returned no useful new evidence, your next turn\n"
    "   should call `done_gathering`. Otherwise CONTINUE gathering.\n"
    "Reply with JSON of the form {\"thought\": \"...\"} containing your reflection. "
    "Do NOT issue a tool call on this turn."
)

# Shared with the eval judge; re-exported so existing callers keep working.
from repi.llm.json_utils import parse_llm_response  # noqa: F401


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
    timestamp: datetime = field(default_factory=_dh.now)
    # `kind` classifies special turns. "reflection" = forced re-plan (no tool call);
    # None = normal thought → action → observation step.
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

class ReactInvestigationLoop:
    def __init__(
        self,
        llm: LLMProvider,
        tools: dict[str, Callable],
        known_services: list[str],
        pool: Optional[asyncpg.Pool] = None,
        store: Optional[InvestigationStore] = None,
        max_iterations: int = 10,
        min_iteration_delay: float = 2.0,
        enable_reflection: bool = True,
        reflection_interval: int = 3,
        max_reflections: int = 2,
        llm_max_calls_per_min: int = 60,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.known_services = known_services
        self.pool = pool
        # Action-step budget; reflection turns and null-action re-prompts
        # do not consume it.
        self.max_iterations = max_iterations
        self.min_iteration_delay = min_iteration_delay
        self.store = store
        self.enable_reflection = enable_reflection
        self.reflection_interval = reflection_interval
        self.max_reflections = max_reflections
        self.llm_max_calls_per_min = llm_max_calls_per_min
        self._llm_call_timestamps: list[float] = []

    @staticmethod
    def _ledger_key(tool_name: str, args: dict) -> str:
        """Stable hash key for a tool call: name + JSON-with-sorted-keys.
        Sorted keys means {"a":1,"b":2} and {"b":2,"a":1} dedupe identically."""
        try:
            normalized = json.dumps(args or {}, sort_keys=True, default=str)
        except (TypeError, ValueError):
            normalized = repr(args)
        return f"{tool_name}::{normalized}"

    @staticmethod
    def _ledger_summary(ledger: dict[str, dict]) -> str:
        """One-line-per-entry summary of every tool call already issued."""
        if not ledger:
            return ""
        lines = []
        for entry in ledger.values():
            lines.append(f"- {entry['tool_name']}({json.dumps(entry['args'], default=str, sort_keys=True)})")
        return "TOOLS ALREADY CALLED (do not repeat with identical args):\n" + "\n".join(lines)

    async def _wait_for_rate_limit(self):
        now = time.time()
        self._llm_call_timestamps = [t for t in self._llm_call_timestamps if now - t < 60]
        while len(self._llm_call_timestamps) >= self.llm_max_calls_per_min:
            wait_time = 60 - (now - self._llm_call_timestamps[0]) + 1
            logger.warning(f"Rate limit: Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            now = time.time()
            self._llm_call_timestamps = [t for t in self._llm_call_timestamps if now - t < 60]
        self._llm_call_timestamps.append(now)

    # Caps for what a single observation may contribute to the LLM
    # conversation. Tool results are re-sent on EVERY subsequent turn, so an
    # uncapped scan_window result multiplies across the whole loop — this is
    # the main driver of token-per-minute 429s. The full, untruncated result
    # is still persisted to the DB and the tool ledger.
    MAX_OBS_ITEMS = 10
    MAX_OBS_TEXT_CHARS = 300
    MAX_OBS_TOTAL_CHARS = 6000

    @classmethod
    def _compact_observation(cls, result: Any) -> str:
        """Serialize a tool result for the LLM conversation, clipping long
        lists and long text fields with explicit markers so the model knows
        evidence was elided (and can narrow its next query)."""

        def _walk(node: Any, max_items: int, max_chars: int) -> Any:
            if isinstance(node, dict):
                return {k: _walk(v, max_items, max_chars) for k, v in node.items()}
            if isinstance(node, list):
                clipped = [_walk(x, max_items, max_chars) for x in node[:max_items]]
                if len(node) > max_items:
                    clipped.append(f"... {len(node) - max_items} more items truncated")
                return clipped
            if isinstance(node, str) and len(node) > max_chars:
                return node[:max_chars] + "...[truncated]"
            return node

        s = json.dumps(_walk(result, cls.MAX_OBS_ITEMS, cls.MAX_OBS_TEXT_CHARS), default=str)
        if len(s) > cls.MAX_OBS_TOTAL_CHARS:
            # Re-walk with much tighter caps rather than slicing the JSON
            # string (which would hand the model malformed JSON).
            s = json.dumps(_walk(result, 3, 120), default=str)
        if len(s) > cls.MAX_OBS_TOTAL_CHARS:
            # Pathological shape (e.g. hundreds of keys) — wrap a hard slice
            # inside a fresh JSON object so the payload stays parseable.
            s = json.dumps({
                "note": "observation too large; showing a truncated excerpt",
                "excerpt": s[:cls.MAX_OBS_TOTAL_CHARS],
            })
        return s

    def _extract_chunks(self, tool_result: Any) -> list[dict]:
        """Collect every dict-with-chunk_id from a tool result. Walks nested
        list-valued fields (e.g. scan_window's `logs` and `pre_context_logs`)
        so chunk-bearing observations get persisted as evidence regardless of
        how the tool wraps its output."""
        chunks: list[dict] = []
        seen: set[str] = set()

        def _maybe_append(item: Any) -> None:
            if isinstance(item, dict):
                cid = item.get("chunk_id")
                if cid and cid not in seen:
                    seen.add(cid)
                    chunks.append(item)

        if isinstance(tool_result, list):
            for item in tool_result:
                _maybe_append(item)
        elif isinstance(tool_result, dict):
            _maybe_append(tool_result)
            for value in tool_result.values():
                if isinstance(value, list):
                    for item in value:
                        _maybe_append(item)
        return chunks

    async def investigate(
        self,
        query: str,
        investigation_id: Optional[UUID] = None,
        on_step: Optional[Callable[[InvestigationStep], Awaitable[None]]] = None,
        on_phase_change: Optional[Callable[[str], Awaitable[None]]] = None,
        known_services: list[str] | None = None,
        resume: bool = True,
    ) -> InvestigationResult:
        if known_services:
            self.known_services = known_services

        start_time = time.time()
        
        # --- PERSISTENCE: Resume or Create ---
        investigation_obj = None
        existing_steps = []
        evidence_chunks = []
        
        if self.store:
            if investigation_id:
                investigation_obj = await self.store.get_by_id(investigation_id)
            elif resume:
                investigation_obj = await self.store.get_or_create(query)
            else:
                investigation_obj = await self.store.create(query)
            existing_steps = await self.store.get_steps(investigation_obj.id)
            chunks_obj = await self.store.get_chunks(investigation_obj.id)
            evidence_chunks = [
                {
                    "chunk_id": c.chunk_id,
                    "service": c.service,
                    "timestamp": c.timestamp,
                    "text": c.message
                } for c in chunks_obj
            ]
        
        # --- 1. INTENT RESOLUTION ---
        resolved_intent = None

        last_step = existing_steps[-1] if existing_steps else None
        clarified_query = query
        if last_step and last_step.action and (last_step.action.get("name") == "ask_user" or last_step.action.get("tool") == "ask_user"):
            if last_step.observation and last_step.observation.get("result"):
                reply = last_step.observation["result"].get("reply", "")
                clarified_query = f"{query} (User Clarification: {reply})"
                logger.info(f"Resuming with clarified query: {clarified_query}")

        post_clarification = clarified_query != query

        if not existing_steps or post_clarification:
            now = _dh.now()
            resolution = resolve_intent(clarified_query, self.known_services, now)
            logger.info(f"Intent Resolution for '{clarified_query}': {resolution}")

            if isinstance(resolution, ClarificationNeeded):
                if post_clarification:
                    # Single-round guarantee: already clarified once — commit with widest defaults
                    logger.warning(
                        f"Still ambiguous after clarification ({resolution.missing_dims}). "
                        "Proceeding with widest-default window (last 24h)."
                    )
                    resolution = ResolvedIntent(
                        time_from=_dh.ago(days=1),
                        time_to=_dh.now(),
                        services=[],
                        symptoms=[],
                        assumed=[
                            f"time could not be resolved after clarification — defaulting to last 24 hours",
                            f"clarification was: {clarified_query}",
                        ],
                    )
                else:
                    thought_text = "I need to clarify the request before I can proceed."
                    action_data = {"name": "ask_user", "args": {"question": resolution.question}}

                    if self.store:
                        # Only add if it's not already the same question (to avoid loops)
                        if not last_step or last_step.action.get("args", {}).get("question") != resolution.question:
                            await self.store.add_step(
                                investigation_id=investigation_obj.id,
                                step_number=len(existing_steps) + 1,
                                thought=thought_text,
                                action=action_data
                            )
                        await self.store.set_awaiting_clarification(investigation_obj.id, resolution.question)

                    step = InvestigationStep(len(existing_steps) + 1, Thought(thought_text), Action(ToolCall(name="ask_user", args=action_data["args"])))
                    if on_step: await on_step(step)

                    return InvestigationResult(
                        id=str(investigation_obj.id),
                        query=query,
                        steps=[step],
                        answer="Awaiting clarification...",
                        evidence_chunk_ids=[],
                        confidence="low",
                        duration_seconds=time.time() - start_time
                    )

            resolved_intent = resolution

        # --- 2. AUTO SWEEP ---
        # `tool_call_ledger` dedupes identical tool invocations across
        # iterations: hash → {tool_name, args, result}. The summary is appended to
        # the system message each turn so the LLM knows what's already been tried.
        tool_call_ledger: dict[str, dict] = {}

        # Signal the gathering phase has begun (consumed by SSE stream).
        if on_phase_change:
            try:
                await on_phase_change("gathering")
            except Exception:
                logger.debug("on_phase_change(gathering) hook raised", exc_info=True)

        messages = [
            Message(role="system", content=self._build_system_prompt()),
            Message(role="user", content=query)
        ]

        if resolved_intent and self.pool and (not existing_steps or post_clarification):
            if resolved_intent.time_from is None:
                # No time window — auto_sweep would query the entire corpus and
                # drown the LLM in unrelated noise. Inject an entity/service-keyed
                # priming message instead and let the LLM pick its first tool.
                priming_lines = ["RAG CONTEXT:"]
                priming_lines.append(
                    f"- entities mentioned: {resolved_intent.entities or 'none'}"
                )
                priming_lines.append(
                    f"- services mentioned: {resolved_intent.services or 'none'}"
                )
                priming_lines.append(
                    "- no time window — use find_logs_by_id (for entities) "
                    "or search_logs with null time_from/time_to (for services)."
                )
                if resolved_intent.assumed:
                    priming_lines.append("")
                    priming_lines.append("ASSUMPTIONS:")
                    priming_lines.extend(f"- {a}" for a in resolved_intent.assumed)
                messages.append(Message(role="user", content="\n".join(priming_lines)))
            else:
                sweep_results = await auto_sweep(
                    pool=self.pool,
                    time_from=resolved_intent.time_from,
                    time_to=resolved_intent.time_to,
                    exclude_services=[]
                )

                sweep_msg = f"SWEEP CONTEXT:\n{self._compact_observation(sweep_results)}\n\n"
                if resolved_intent.assumed:
                    sweep_msg += "ASSUMPTIONS:\n" + "\n".join(f"- {a}" for a in resolved_intent.assumed) + "\n"

                messages.append(Message(role="user", content=sweep_msg))
            
        processed_steps = []
        start_at_iteration = 0
        
        for s in existing_steps:
            thought = Thought(content=s.thought)
            action = None
            observation = None
            
            if s.action:
                action = Action(tool_call=ToolCall(name=s.action.get("name") or s.action.get("tool"), args=s.action["args"]))
            if s.observation:
                observation = Observation(tool_result=ToolResult(
                    tool_name=s.observation.get("tool_name", "unknown"),
                    args=s.observation.get("args", {}),
                    result=s.observation.get("result"),
                    error=s.observation.get("error")
                ))
            
            step = InvestigationStep(
                s.step_number,
                thought,
                action,
                observation,
                s.created_at,
                kind=getattr(s, "kind", None),
            )
            processed_steps.append(step)
            
            llm_payload = {"thought": s.thought}
            if action:
                llm_payload["action"] = {"tool": action.tool_call.name, "args": action.tool_call.args}

            messages.append(Message(role="assistant", content=json.dumps(llm_payload)))
            if observation:
                res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                messages.append(Message(role="user", content=f"Observation:\n{self._compact_observation(res)}"))

            # Seed the ledger from replayed steps so dedupe survives resume.
            if action and observation and observation.tool_result.result is not None:
                ledger_key = self._ledger_key(action.tool_call.name, action.tool_call.args)
                tool_call_ledger.setdefault(ledger_key, {
                    "tool_name": action.tool_call.name,
                    "args": action.tool_call.args,
                    "result": observation.tool_result.result,
                })

            start_at_iteration = max(start_at_iteration, s.step_number)

        # --- Action / reflection counters -----------------------------------
        # `actions_taken` is the only thing that consumes `max_iterations`.
        # Reflection turns and null-action re-prompts do NOT decrement the
        # action budget — they live on their own counters.
        actions_taken = 0
        reflections_used = 0
        action_steps_since_reflection = 0
        consecutive_empty_tool_calls = 0
        for s in existing_steps:
            if getattr(s, "kind", None) == "reflection":
                action_steps_since_reflection = 0
                reflections_used += 1
            elif getattr(s, "kind", None) is None and s.action:
                action_steps_since_reflection += 1

        next_step_number = start_at_iteration + 1
        gathering_exit_reason = "max_actions_reached"
        null_action_reprompted_this_turn = False

        while actions_taken < self.max_iterations:
            if next_step_number > start_at_iteration + 1:
                await asyncio.sleep(self.min_iteration_delay)

            # --- Reflection turn ------------------------------------------------
            if (
                self.enable_reflection
                and self.reflection_interval > 0
                and reflections_used < self.max_reflections
                and action_steps_since_reflection >= self.reflection_interval
            ):
                messages.append(Message(role="user", content=REFLECTION_PROMPT))
                raw_reflection = None
                for _refl_retry in range(3):
                    try:
                        await self._wait_for_rate_limit()
                        raw_reflection = await self.llm.complete(messages)
                        break
                    except LLMBadRequestError as e:
                        # Bad payload/auth — retrying the identical request can't succeed.
                        logger.error(f"Reflection {next_step_number}: non-retryable LLM error: {e}")
                        break
                    except Exception as e:
                        logger.warning(f"Reflection {next_step_number} attempt {_refl_retry+1}/3 failed: {e}")
                        if _refl_retry < 2:
                            delay = 15 * (2 ** _refl_retry)
                            if isinstance(e, LLMRateLimitError) and e.retry_after:
                                delay = e.retry_after + 1
                            await asyncio.sleep(delay)

                if raw_reflection is None:
                    logger.error(f"Reflection {next_step_number}: LLM call failed after 3 retries, skipping")
                    if messages and messages[-1].content == REFLECTION_PROMPT:
                        messages.pop()
                    action_steps_since_reflection = 0
                    reflections_used += 1
                    continue

                if self.store and investigation_obj:
                    await self.store.increment_llm_calls(investigation_obj.id)

                try:
                    parsed_reflection = parse_llm_response(raw_reflection)
                    reflection_thought = parsed_reflection.get("thought", "") or raw_reflection
                except Exception:
                    reflection_thought = raw_reflection

                # The reflection prompt invites rich structured reasoning, so the
                # LLM sometimes emits `thought` as a dict/list. The DB column is
                # TEXT — coerce to a JSON string in that case.
                if not isinstance(reflection_thought, str):
                    try:
                        reflection_thought = json.dumps(reflection_thought, default=str)
                    except (TypeError, ValueError):
                        reflection_thought = str(reflection_thought)

                reflection_step = InvestigationStep(
                    next_step_number,
                    Thought(reflection_thought),
                    None,
                    None,
                    kind="reflection",
                )
                processed_steps.append(reflection_step)

                if self.store and investigation_obj:
                    await self.store.add_step(
                        investigation_id=investigation_obj.id,
                        step_number=next_step_number,
                        thought=reflection_thought,
                        action=None,
                        observation=None,
                        kind="reflection",
                    )

                if on_step:
                    await on_step(reflection_step)

                # Keep the reflection in the rolling conversation so the next
                # turn's action is anchored to the re-plan.
                messages.append(Message(role="assistant", content=raw_reflection))

                next_step_number += 1
                action_steps_since_reflection = 0
                reflections_used += 1
                continue

            # --- Graduated finalize prompts ---------------------------------
            # As the action budget runs low, escalate toward exit. The loop
            # never produces the final answer itself — `done_gathering` (or
            # exhausting the budget) hands off to the compiler.
            actions_remaining = self.max_iterations - actions_taken
            if actions_remaining == 2:
                messages.append(Message(
                    role="user",
                    content=(
                        "You have 2 actions left before gathering ends. Only "
                        "issue a tool call if it would materially change the "
                        "final answer; otherwise call `done_gathering`."
                    ),
                ))
            elif actions_remaining == 1:
                messages.append(Message(
                    role="user",
                    content=(
                        "Last action. The next turn should either call "
                        "`done_gathering` or one final tool call. After this "
                        "turn the gathering phase ends."
                    ),
                ))

            # --- Ensure last message is user/system before calling LLM -----
            if messages and messages[-1].role == "assistant":
                messages.append(Message(role="user", content="Continue gathering evidence."))

            # --- LLM call with retry -----------------------------------------------
            raw_response = None
            for _llm_retry in range(3):
                try:
                    await self._wait_for_rate_limit()
                    raw_response = await self.llm.complete(messages)
                    break
                except LLMBadRequestError as e:
                    # Bad payload/auth — retrying the identical request can't succeed.
                    logger.error(f"Step {next_step_number}: non-retryable LLM error: {e}")
                    break
                except Exception as e:
                    logger.warning(f"Step {next_step_number} LLM call attempt {_llm_retry+1}/3 failed: {e}")
                    if _llm_retry < 2:
                        delay = 15 * (2 ** _llm_retry)
                        if isinstance(e, LLMRateLimitError) and e.retry_after:
                            delay = e.retry_after + 1
                        await asyncio.sleep(delay)

            if raw_response is None:
                logger.error(f"Step {next_step_number}: LLM call failed after 3 retries, ending gathering")
                gathering_exit_reason = "llm_call_failed_repeatedly"
                break

            if self.store and investigation_obj:
                await self.store.increment_llm_calls(investigation_obj.id)

            try:
                parsed = parse_llm_response(raw_response)

                _thought_raw = parsed.get("thought", "")
                if not isinstance(_thought_raw, str):
                    try:
                        _thought_raw = json.dumps(_thought_raw, default=str)
                    except (TypeError, ValueError):
                        _thought_raw = str(_thought_raw)
                thought = Thought(content=_thought_raw)
                action = None
                observation = None
                signal_done = False

                is_repeat_call = False
                if "action" in parsed and isinstance(parsed["action"], dict):
                    tool_name = parsed["action"].get("tool")
                    tool_args = parsed["action"].get("args", {}) or {}

                    if tool_name in (DONE_GATHERING_TOOL, LEGACY_SUBMIT_TOOL):
                        signal_done = True
                        gathering_exit_reason = (
                            tool_args.get("reason", "model_signaled_done")
                            if isinstance(tool_args, dict)
                            else "model_signaled_done"
                        )
                        action = Action(tool_call=ToolCall(
                            name=DONE_GATHERING_TOOL,
                            args={"reason": str(gathering_exit_reason)},
                        ))
                    elif tool_name:
                        action = Action(tool_call=ToolCall(name=tool_name, args=tool_args))

                        if tool_name in self.tools:
                            ledger_key = self._ledger_key(tool_name, tool_args)
                            cached = tool_call_ledger.get(ledger_key)
                            if cached is not None:
                                is_repeat_call = True
                                observation = Observation(tool_result=ToolResult(
                                    tool_name=tool_name,
                                    args=tool_args,
                                    result=cached["result"],
                                ))
                                logger.info(f"Repeat tool call dedup'd: {tool_name}({tool_args})")
                            else:
                                try:
                                    result = await self.tools[tool_name](**tool_args)
                                    observation = Observation(tool_result=ToolResult(
                                        tool_name=tool_name,
                                        args=tool_args,
                                        result=result
                                    ))
                                    tool_call_ledger[ledger_key] = {
                                        "tool_name": tool_name,
                                        "args": tool_args,
                                        "result": result,
                                    }
                                    new_chunks = self._extract_chunks(result)
                                    if not new_chunks:
                                        consecutive_empty_tool_calls += 1
                                    else:
                                        consecutive_empty_tool_calls = 0
                                    if self.store:
                                        await self.store.add_chunks(investigation_obj.id, new_chunks)
                                except Exception as e:
                                    logger.error(f"Tool failed: {e}")
                                    observation = Observation(tool_result=ToolResult(
                                        tool_name=tool_name, args=tool_args, result=None, error=str(e)
                                    ))
                                    consecutive_empty_tool_calls += 1
                        else:
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name, args=tool_args, result=None, error=f"Unknown tool '{tool_name}'"
                            ))

                # --- Null-action guard ---------------------------------------
                # If the model produced neither a tool call nor a done signal,
                # give it ONE chance to recover without spending an action.
                if action is None and not signal_done:
                    if not null_action_reprompted_this_turn:
                        null_action_reprompted_this_turn = True
                        messages.append(Message(role="assistant", content=raw_response))
                        messages.append(Message(
                            role="user",
                            content=(
                                "Your previous reply had no tool call. Reply again "
                                "with a JSON object containing an `action` — either a "
                                "real tool call or `done_gathering` if you are done."
                            ),
                        ))
                        continue
                    # Already re-prompted once this turn; force exit so the
                    # compiler can still produce an answer.
                    gathering_exit_reason = "model_emitted_thought_only_twice"
                    logger.warning(
                        "Step %d: model gave no action twice in a row; exiting gathering",
                        next_step_number,
                    )
                    break

                null_action_reprompted_this_turn = False

                # --- Persist the step (signal or real action) ----------------
                kind = "signal" if signal_done else None
                step = InvestigationStep(next_step_number, thought, action, observation, kind=kind)
                processed_steps.append(step)

                if self.store:
                    await self.store.add_step(
                        investigation_id=investigation_obj.id,
                        step_number=next_step_number,
                        thought=thought.content,
                        action=asdict(action.tool_call) if action else None,
                        observation=asdict(observation.tool_result) if observation else None,
                        kind=kind,
                    )

                if on_step:
                    await on_step(step)

                next_step_number += 1

                if signal_done:
                    break

                # Real action steps advance the budget and the reflection counter.
                actions_taken += 1
                action_steps_since_reflection += 1

                # Stall detection: two empty tool calls in a row exits gathering.
                if consecutive_empty_tool_calls >= 2:
                    gathering_exit_reason = "stalled_no_new_evidence"
                    logger.info(
                        "Exiting gathering early: %d consecutive tool calls returned no new chunks",
                        consecutive_empty_tool_calls,
                    )
                    break

                messages.append(Message(role="assistant", content=raw_response))
                if observation and observation.tool_result:
                    res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                    prefix = "(repeat call — returning cached result)\n" if is_repeat_call else ""
                    messages.append(Message(role="user", content=f"{prefix}Observation:\n{self._compact_observation(res)}"))

                if tool_call_ledger:
                    messages[0] = Message(
                        role="system",
                        content=self._build_system_prompt() + "\n\n" + self._ledger_summary(tool_call_ledger),
                    )

            except Exception as e:
                logger.error(f"Step {next_step_number} failed during processing: {e}")
                if messages and messages[-1].role == "assistant":
                    messages.pop()
                continue

        # --- Compile phase --------------------------------------------------
        # Gathering is done. Hand off to the compiler, which runs a single,
        # focused LLM call against the evidence we collected and produces a
        # validated InvestigationAnswer. The compiler internally falls back
        # to a deterministic synthesis if its own LLM call fails twice.
        chunks_obj = await self.store.get_chunks(investigation_obj.id) if self.store else []
        evidence_chunks = [
            {
                "chunk_id": c.chunk_id,
                "service": c.service,
                "timestamp": str(c.timestamp),
                "message": c.message,
            }
            for c in chunks_obj
        ]

        if on_phase_change:
            try:
                await on_phase_change("compiling")
            except Exception:
                logger.debug("on_phase_change(compiling) hook raised", exc_info=True)

        recent_thoughts = [
            s.thought.content for s in processed_steps[-4:] if s.thought and s.thought.content
        ]

        try:
            compile_result = await compile_answer(
                llm=self.llm,
                query=query,
                resolved_intent=resolved_intent,
                evidence=evidence_chunks,
                tool_ledger=tool_call_ledger,
                recent_thoughts=recent_thoughts,
                known_services=self.known_services,
            )
            final_answer_dict = compile_result.answer
            compile_source = compile_result.source
            compile_attempts = compile_result.attempts
            floor_adjustments = compile_result.floor_adjustments
        except Exception as e:
            logger.error("Compiler raised; falling back to deterministic synth: %s", e)
            final_answer_dict = synthesize_answer(
                query=query,
                resolved_intent=resolved_intent,
                evidence=evidence_chunks,
                tool_ledger=tool_call_ledger,
                extra_gaps=[f"compile_answer raised: {e}"],
            )
            compile_source = "deterministic_exception"
            compile_attempts = 0
            floor_adjustments = []

        # Persist the compile step so the trace shows the phase boundary.
        compile_thought = (
            f"Compiled answer from {len(evidence_chunks)} evidence chunks across "
            f"{len({c.get('service') for c in evidence_chunks if c.get('service')})} services "
            f"(source={compile_source}, attempts={compile_attempts}, "
            f"exit_reason={gathering_exit_reason})"
        )
        compile_step = InvestigationStep(
            next_step_number,
            Thought(compile_thought),
            None,
            None,
            kind="compile",
        )
        processed_steps.append(compile_step)
        if self.store:
            await self.store.add_step(
                investigation_id=investigation_obj.id,
                step_number=next_step_number,
                thought=compile_thought,
                action=None,
                observation=None,
                kind="compile",
            )
        if on_step:
            await on_step(compile_step)

        if self.store and investigation_obj:
            await self.store.finalize(investigation_obj.id, json.dumps(final_answer_dict))

        stats = {
            "iterations_used": actions_taken,
            "reflections_used": reflections_used,
            "chunks_gathered": len(evidence_chunks),
            "tools_called": sorted({e["tool_name"] for e in tool_call_ledger.values()}),
            "compile_source": compile_source,
            "compile_attempts": compile_attempts,
            "floor_adjustments": floor_adjustments,
            "gathering_exit_reason": gathering_exit_reason,
        }

        if on_phase_change:
            try:
                await on_phase_change("done")
            except Exception:
                logger.debug("on_phase_change(done) hook raised", exc_info=True)

        return InvestigationResult(
            id=str(investigation_obj.id) if investigation_obj else "unknown",
            query=query,
            steps=processed_steps,
            answer=json.dumps(final_answer_dict, indent=2),
            evidence_chunk_ids=[c.chunk_id for c in chunks_obj] if self.store else [],
            confidence=final_answer_dict.get("confidence", "low"),
            duration_seconds=time.time() - start_time,
            evidence=evidence_chunks,
            stats=stats,
        )

    def _build_system_prompt(self) -> str:
        # Don't advertise `submit_answer` in the schema — this loop only
        # gathers; the compiler produces the final answer.
        gathering_tools = {k: v for k, v in TOOL_SCHEMAS.items() if k != LEGACY_SUBMIT_TOOL}
        return f"""You are a senior SRE gathering evidence about an incident.
Postgres is the source of truth for this investigation.

KNOWN SERVICES: {self.known_services}
TOOLS: {json.dumps(gathering_tools, indent=2)}

YOUR ROLE: You are an EVIDENCE GATHERER. A separate "compile" step will turn
the evidence you collect into the final structured answer. You do NOT produce
that answer yourself.

RESPONSE FORMAT (use exactly this shape on every turn — no exceptions):
{{ "thought": "...", "action": {{ "tool": "<tool_name>", "args": {{...}} }} }}

When you believe you have gathered enough evidence (or that further
investigation will not change the answer), signal exit by calling
`done_gathering`:
{{ "thought": "...", "action": {{ "tool": "done_gathering", "args": {{ "reason": "..." }} }} }}

GATHERING PRINCIPLES:
1. ENTITY FIRST. If the query mentions a literal identifier (UUID, W3C trace
   or span id, ULID, a prefixed ID like ch_xxx / pi_xxx / cus_xxx, an AWS
   resource id like i-0abc…, a git SHA, or any other unique token), call
   `find_logs_by_id` on the FIRST action turn. Semantic + FTS retrieval
   will often miss specific tokens because the English tokenizer fragments
   them and embeddings don't preserve literal token identity.
2. ALWAYS correlate logs cross-service. `scan_window` is usually the right
   first call when investigating a TIME WINDOW (no entity in play) — it
   returns ERRORS plus pre-context for each service that emitted them.
3. Don't repeat tool calls with identical arguments — the dispatcher
   dedupes them, but you still waste a turn.
4. If a tool call returns nothing useful, vary the arguments (different
   service, wider window, different level filter) before giving up on
   that line of inquiry.
5. If two consecutive tool calls return no new evidence, call
   `done_gathering` — there is no value in spamming the dispatcher.
6. When NO time window was provided, do NOT pass time_from/time_to to
   `search_logs`/`scan_window`; rely on `find_logs_by_id` and unbounded
   searches keyed off the entity/service signal you do have.
7. Do NOT emit a "Final Answer:" prefix or fill in any
   InvestigationAnswer schema. The compile step will produce that.

Current UTC: {_dh.to_iso(_dh.now())}
"""

def asdict(obj):
    from dataclasses import asdict as _asdict
    return _asdict(obj)
