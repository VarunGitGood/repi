from __future__ import annotations
import json
import logging
import asyncio
import time
from uuid import UUID
from typing import Any, Optional, Callable, Awaitable

import asyncpg

from repi.core.dates import default_date_handler as _dh
from repi.llm.adapters import LLMRateLimitError, LLMBadRequestError
from repi.llm.provider import LLMProvider, Message
from repi.investigation.tools import ToolCall, ToolResult, TOOL_SCHEMAS
from repi.investigation.store import InvestigationStore
from repi.intent.resolver import resolve as resolve_intent, ResolvedIntent, ClarificationNeeded
from repi.investigation.sweep import auto_sweep
from repi.investigation.compiler import compile_answer, synthesize_answer
from repi.investigation.sanitize import sanitize_query
from repi.investigation.state import (
    Phase,
    InvestigationState,
    LoopDeps,
    Thought,
    Action,
    Observation,
    InvestigationStep,
    InvestigationResult,
)

logger = logging.getLogger(__name__)


DONE_GATHERING_TOOL = "done_gathering"
LEGACY_SUBMIT_TOOL = "submit_answer"

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


# ─── Observation compaction ──────────────────────────────────────────────────

MAX_OBS_ITEMS = 10
MAX_OBS_TEXT_CHARS = 300
MAX_OBS_TOTAL_CHARS = 6000


def _compact_observation(result: Any) -> str:
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

    s = json.dumps(_walk(result, MAX_OBS_ITEMS, MAX_OBS_TEXT_CHARS), default=str)
    if len(s) > MAX_OBS_TOTAL_CHARS:
        s = json.dumps(_walk(result, 3, 120), default=str)
    if len(s) > MAX_OBS_TOTAL_CHARS:
        s = json.dumps({
            "note": "observation too large; showing a truncated excerpt",
            "excerpt": s[:MAX_OBS_TOTAL_CHARS],
        })
    return s


def _extract_chunks(tool_result: Any) -> list[dict]:
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


def _is_degenerate_output(text: str, threshold: int = 4000, repeat_ratio: float = 0.4) -> bool:
    if len(text) < threshold:
        return False
    chunk_size = 200
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    if len(chunks) < 3:
        return False
    unique = len(set(chunks))
    return (unique / len(chunks)) < repeat_ratio


async def _auto_fill_unchecked_services(state: InvestigationState, deps: LoopDeps) -> None:
    unchecked = _unchecked_services(state.tool_call_ledger, deps.known_services)
    if not unchecked or "get_service_summary" not in deps.tools:
        return
    logger.info("Auto-filling %d unchecked services: %s", len(unchecked), unchecked)
    for svc in unchecked:
        try:
            result = await deps.tools["get_service_summary"](service=svc)
            lkey = _ledger_key("get_service_summary", {"service": svc})
            state.tool_call_ledger[lkey] = {
                "tool_name": "get_service_summary",
                "args": {"service": svc},
                "result": result,
            }
            new_chunks = _extract_chunks(result)
            if deps.store and new_chunks:
                await deps.store.add_chunks(state.investigation_id, new_chunks)
        except Exception as e:
            logger.warning("Auto-fill for %s failed: %s", svc, e)


def _unchecked_services(ledger: dict[str, dict], known_services: list[str]) -> list[str]:
    queried = set()
    for entry in ledger.values():
        args = entry.get("args", {})
        svc = args.get("service") or args.get("services")
        if isinstance(svc, str) and svc:
            queried.add(svc)
        elif isinstance(svc, list):
            queried.update(svc)
        result = entry.get("result")
        if isinstance(result, dict):
            for key in result:
                if key in known_services:
                    queried.add(key)
    return [s for s in known_services if s not in queried]


def _count_errors_per_service(sweep_results: Any, known_services: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {svc: 0 for svc in known_services}
    if isinstance(sweep_results, dict):
        for svc, entries in sweep_results.items():
            if svc in counts and isinstance(entries, list):
                counts[svc] = len(entries)
            elif isinstance(entries, dict):
                for sub_svc, sub_entries in entries.items():
                    if sub_svc in counts and isinstance(sub_entries, list):
                        counts[sub_svc] = len(sub_entries)
    return counts


# ─── Ledger helpers ──────────────────────────────────────────────────────────

def _ledger_key(tool_name: str, args: dict) -> str:
    try:
        normalized = json.dumps(args or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        normalized = repr(args)
    return f"{tool_name}::{normalized}"


def _ledger_summary(ledger: dict[str, dict]) -> str:
    if not ledger:
        return ""
    lines = []
    for entry in ledger.values():
        lines.append(f"- {entry['tool_name']}({json.dumps(entry['args'], default=str, sort_keys=True)})")
    return "TOOLS ALREADY CALLED (do not repeat with identical args):\n" + "\n".join(lines)


# ─── Rate limiting ───────────────────────────────────────────────────────────

async def _wait_for_rate_limit(deps: LoopDeps):
    now = time.time()
    deps.llm_call_timestamps = [t for t in deps.llm_call_timestamps if now - t < 60]
    while len(deps.llm_call_timestamps) >= deps.llm_max_calls_per_min:
        wait_time = 60 - (now - deps.llm_call_timestamps[0]) + 1
        logger.warning(f"Rate limit: Waiting {wait_time:.1f}s...")
        await asyncio.sleep(wait_time)
        now = time.time()
        deps.llm_call_timestamps = [t for t in deps.llm_call_timestamps if now - t < 60]
    deps.llm_call_timestamps.append(now)


# ─── LLM call with retry ────────────────────────────────────────────────────

async def _llm_call_with_retry(
    deps: LoopDeps,
    messages: list[Message],
    step_label: str,
) -> str | None:
    for attempt in range(3):
        try:
            await _wait_for_rate_limit(deps)
            return await deps.llm.complete(messages, max_tokens=8000)
        except LLMBadRequestError as e:
            logger.error(f"{step_label}: non-retryable LLM error: {e}")
            return None
        except Exception as e:
            logger.warning(f"{step_label} attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                delay = 15 * (2 ** attempt)
                if isinstance(e, LLMRateLimitError) and e.retry_after:
                    delay = e.retry_after + 1
                await asyncio.sleep(delay)
    return None


# ─── System prompt builder ───────────────────────────────────────────────────

def _build_system_prompt(known_services: list[str]) -> str:
    gathering_tools = {k: v for k, v in TOOL_SCHEMAS.items() if k != LEGACY_SUBMIT_TOOL}
    return f"""You are a senior SRE gathering evidence about an incident.
Postgres is the source of truth for this investigation.

KNOWN SERVICES: {known_services}
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
3. INVESTIGATE EVERY KNOWN SERVICE. Before calling `done_gathering`, ensure
   you have checked each service in KNOWN SERVICES for relevant activity.
   Services that show no errors still matter — you need evidence to rule
   them out. Use `get_service_summary` or `scan_window` filtered by service
   to confirm a service is uninvolved.
4. Don't repeat tool calls with identical arguments — the dispatcher
   dedupes them, but you still waste a turn.
5. If a tool call returns nothing useful, vary the arguments (different
   service, wider window, different level filter) before giving up on
   that line of inquiry.
6. If two consecutive tool calls return no new evidence, call
   `done_gathering` — there is no value in spamming the dispatcher.
7. When NO time window was provided, do NOT pass time_from/time_to to
   `search_logs`/`scan_window`; rely on `find_logs_by_id` and unbounded
   searches keyed off the entity/service signal you do have.
8. Do NOT emit a "Final Answer:" prefix or fill in any
   InvestigationAnswer schema. The compile step will produce that.

Current UTC: {_dh.to_iso(_dh.now())}
"""


# ─── Phase handlers ──────────────────────────────────────────────────────────

async def handle_resolving(state: InvestigationState, deps: LoopDeps) -> InvestigationState:
    now = _dh.now()
    clarified_query = sanitize_query(state.query)

    if state.post_clarification:
        last_step_obs = None
        if deps.store:
            existing_steps = await deps.store.get_steps(state.investigation_id)
            last_step = existing_steps[-1] if existing_steps else None
            if (
                last_step
                and last_step.action
                and (last_step.action.get("name") == "ask_user" or last_step.action.get("tool") == "ask_user")
                and last_step.observation
                and last_step.observation.get("result")
            ):
                reply = last_step.observation["result"].get("reply", "")
                clarified_query = f"{state.query} (User Clarification: {reply})"

    resolution = resolve_intent(clarified_query, deps.known_services, now)
    logger.info(f"Intent Resolution for '{clarified_query}': {resolution}")

    if isinstance(resolution, ClarificationNeeded):
        if state.post_clarification:
            logger.warning(
                f"Still ambiguous after clarification ({resolution.missing_dims}). "
                "Proceeding with widest-default window (last 24h)."
            )
            state.resolved_intent = ResolvedIntent(
                time_from=_dh.ago(days=1),
                time_to=_dh.now(),
                services=[],
                symptoms=[],
                assumed=[
                    "time could not be resolved after clarification — defaulting to last 24 hours",
                    f"clarification was: {clarified_query}",
                ],
            )
            state.phase = Phase.SWEEPING
            return state

        thought_text = "I need to clarify the request before I can proceed."
        action_data = {"name": "ask_user", "args": {"question": resolution.question}}

        if deps.store:
            existing_steps = await deps.store.get_steps(state.investigation_id)
            last_step = existing_steps[-1] if existing_steps else None
            if not last_step or last_step.action.get("args", {}).get("question") != resolution.question:
                await deps.store.add_step(
                    investigation_id=state.investigation_id,
                    step_number=state.next_step_number,
                    thought=thought_text,
                    action=action_data,
                )
            await deps.store.set_awaiting_clarification(state.investigation_id, resolution.question)

        step = InvestigationStep(
            state.next_step_number,
            Thought(thought_text),
            Action(ToolCall(name="ask_user", args=action_data["args"])),
        )
        state.processed_steps.append(step)
        if deps.on_step:
            await deps.on_step(step)

        state.pending_question = resolution.question
        state.phase = Phase.WAITING_CLARIFICATION
        return state

    state.resolved_intent = resolution
    state.phase = Phase.SWEEPING
    return state


async def handle_waiting_clarification(state: InvestigationState, deps: LoopDeps) -> InvestigationState:
    state.post_clarification = True
    state.pending_question = None
    state.phase = Phase.RESOLVING
    return state


async def handle_sweeping(state: InvestigationState, deps: LoopDeps) -> InvestigationState:
    if deps.on_phase_change:
        try:
            await deps.on_phase_change("gathering")
        except Exception:
            logger.debug("on_phase_change(gathering) hook raised", exc_info=True)

    state.messages = [
        Message(role="system", content=_build_system_prompt(deps.known_services)),
        Message(role="user", content=sanitize_query(state.query)),
    ]

    if state.resolved_intent and deps.pool:
        if state.resolved_intent.time_from is None:
            priming_lines = ["RAG CONTEXT:"]
            priming_lines.append(
                f"- entities mentioned: {state.resolved_intent.entities or 'none'}"
            )
            priming_lines.append(
                f"- services mentioned: {state.resolved_intent.services or 'none'}"
            )
            priming_lines.append(
                "- no time window — use find_logs_by_id (for entities) "
                "or search_logs with null time_from/time_to (for services)."
            )
            if state.resolved_intent.assumed:
                priming_lines.append("")
                priming_lines.append("ASSUMPTIONS:")
                priming_lines.extend(f"- {a}" for a in state.resolved_intent.assumed)
            state.messages.append(Message(role="user", content="\n".join(priming_lines)))
        else:
            sweep_results = await auto_sweep(
                pool=deps.pool,
                time_from=state.resolved_intent.time_from,
                time_to=state.resolved_intent.time_to,
                exclude_services=[],
            )
            sweep_msg = f"SWEEP CONTEXT:\n{_compact_observation(sweep_results)}\n\n"

            svc_errors = _count_errors_per_service(sweep_results, deps.known_services)
            if svc_errors:
                sweep_msg += "SERVICE ERROR SUMMARY (you must investigate or rule out every service):\n"
                for svc, count in svc_errors.items():
                    label = f"{count} error(s)" if count > 0 else "no errors"
                    sweep_msg += f"  - {svc}: {label}\n"
                sweep_msg += "\n"

            if state.resolved_intent.assumed:
                sweep_msg += "ASSUMPTIONS:\n" + "\n".join(f"- {a}" for a in state.resolved_intent.assumed) + "\n"
            state.messages.append(Message(role="user", content=sweep_msg))

    planning_nudge = (
        "Before your first tool call, state a brief INVESTIGATION PLAN:\n"
        "1. Which services you will query first and why\n"
        "2. What hypothesis you are testing\n"
        "3. What would change your hypothesis\n"
        "Then proceed with your first tool call."
    )
    state.messages.append(Message(role="user", content=planning_nudge))

    state.phase = Phase.GATHERING
    return state


async def handle_reflecting(state: InvestigationState, deps: LoopDeps) -> InvestigationState:
    state.messages.append(Message(role="user", content=REFLECTION_PROMPT))

    raw_reflection = await _llm_call_with_retry(
        deps, state.messages, f"Reflection {state.next_step_number}"
    )

    if raw_reflection is None:
        logger.error(f"Reflection {state.next_step_number}: LLM call failed after 3 retries, skipping")
        if state.messages and state.messages[-1].content == REFLECTION_PROMPT:
            state.messages.pop()
        state.action_steps_since_reflection = 0
        state.reflections_used += 1
        state.phase = Phase.GATHERING
        return state

    if deps.store:
        await deps.store.increment_llm_calls(state.investigation_id)

    try:
        parsed_reflection = parse_llm_response(raw_reflection)
        reflection_thought = parsed_reflection.get("thought", "") or raw_reflection
    except Exception:
        reflection_thought = raw_reflection

    if not isinstance(reflection_thought, str):
        try:
            reflection_thought = json.dumps(reflection_thought, default=str)
        except (TypeError, ValueError):
            reflection_thought = str(reflection_thought)

    reflection_step = InvestigationStep(
        state.next_step_number,
        Thought(reflection_thought),
        None,
        None,
        kind="reflection",
    )
    state.processed_steps.append(reflection_step)

    if deps.store:
        await deps.store.add_step(
            investigation_id=state.investigation_id,
            step_number=state.next_step_number,
            thought=reflection_thought,
            action=None,
            observation=None,
            kind="reflection",
        )

    if deps.on_step:
        await deps.on_step(reflection_step)

    state.messages.append(Message(role="assistant", content=raw_reflection))
    state.next_step_number += 1
    state.action_steps_since_reflection = 0
    state.reflections_used += 1
    state.phase = Phase.GATHERING
    return state


async def handle_gathering(state: InvestigationState, deps: LoopDeps) -> InvestigationState:
    if state.actions_taken >= deps.max_iterations:
        state.gathering_exit_reason = "max_actions_reached"
        state.phase = Phase.COMPILING
        return state

    # Check if reflection is due
    if (
        deps.enable_reflection
        and deps.reflection_interval > 0
        and state.reflections_used < deps.max_reflections
        and state.action_steps_since_reflection >= deps.reflection_interval
    ):
        state.phase = Phase.REFLECTING
        return state

    # Iteration delay (skip on first step)
    if state.next_step_number > 1 and state.actions_taken > 0:
        await asyncio.sleep(deps.min_iteration_delay)

    # Graduated finalize prompts
    actions_remaining = deps.max_iterations - state.actions_taken
    if actions_remaining == 2:
        state.messages.append(Message(
            role="user",
            content=(
                "You have 2 actions left before gathering ends. Only "
                "issue a tool call if it would materially change the "
                "final answer; otherwise call `done_gathering`."
            ),
        ))
    elif actions_remaining == 1:
        state.messages.append(Message(
            role="user",
            content=(
                "Last action. The next turn should either call "
                "`done_gathering` or one final tool call. After this "
                "turn the gathering phase ends."
            ),
        ))

    # Ensure last message is user/system before calling LLM
    if state.messages and state.messages[-1].role == "assistant":
        state.messages.append(Message(role="user", content="Continue gathering evidence."))

    # LLM call
    raw_response = await _llm_call_with_retry(
        deps, state.messages, f"Step {state.next_step_number}"
    )

    if raw_response is None:
        logger.error(f"Step {state.next_step_number}: LLM call failed after 3 retries, ending gathering")
        state.gathering_exit_reason = "llm_call_failed_repeatedly"
        state.phase = Phase.COMPILING
        return state

    if deps.store:
        await deps.store.increment_llm_calls(state.investigation_id)

    if _is_degenerate_output(raw_response):
        logger.warning("Step %d: degenerate output detected (%d chars), re-prompting",
                        state.next_step_number, len(raw_response))
        state.messages.append(Message(
            role="user",
            content=(
                "Your response was too long and repetitive. "
                "Give a concise thought (under 500 chars) and one tool call."
            ),
        ))
        return state

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
                if state.actions_taken < deps.min_gathering_actions:
                    state.messages.append(Message(role="assistant", content=raw_response))
                    unchecked = _unchecked_services(state.tool_call_ledger, deps.known_services)
                    svc_hint = f" Unchecked services: {', '.join(unchecked)}." if unchecked else ""
                    state.messages.append(Message(
                        role="user",
                        content=(
                            f"Too early to stop — only {state.actions_taken} action(s) taken "
                            f"(minimum {deps.min_gathering_actions}). Investigate further "
                            f"before calling done_gathering.{svc_hint}"
                        ),
                    ))
                    logger.info("Rejected early done_gathering at action %d (min %d)",
                                state.actions_taken, deps.min_gathering_actions)
                    return state

                signal_done = True
                state.gathering_exit_reason = (
                    tool_args.get("reason", "model_signaled_done")
                    if isinstance(tool_args, dict)
                    else "model_signaled_done"
                )
                action = Action(tool_call=ToolCall(
                    name=DONE_GATHERING_TOOL,
                    args={"reason": str(state.gathering_exit_reason)},
                ))
            elif tool_name:
                action = Action(tool_call=ToolCall(name=tool_name, args=tool_args))

                if tool_name in deps.tools:
                    lkey = _ledger_key(tool_name, tool_args)
                    cached = state.tool_call_ledger.get(lkey)
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
                            result = await deps.tools[tool_name](**tool_args)
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name,
                                args=tool_args,
                                result=result,
                            ))
                            state.tool_call_ledger[lkey] = {
                                "tool_name": tool_name,
                                "args": tool_args,
                                "result": result,
                            }
                            new_chunks = _extract_chunks(result)
                            if not new_chunks:
                                state.consecutive_empty_tool_calls += 1
                            else:
                                state.consecutive_empty_tool_calls = 0
                            if deps.store:
                                await deps.store.add_chunks(state.investigation_id, new_chunks)
                        except Exception as e:
                            logger.error(f"Tool failed: {e}")
                            schema_hint = ""
                            if tool_name in TOOL_SCHEMAS:
                                schema_hint = f" Expected args: {json.dumps(TOOL_SCHEMAS[tool_name].get('args', {}))}"
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name, args=tool_args, result=None,
                                error=f"{e}{schema_hint}",
                            ))
                            state.consecutive_empty_tool_calls += 1
                else:
                    observation = Observation(tool_result=ToolResult(
                        tool_name=tool_name, args=tool_args, result=None,
                        error=f"Unknown tool '{tool_name}'",
                    ))

        # Null-action guard
        if action is None and not signal_done:
            if not state.null_action_reprompted:
                state.null_action_reprompted = True
                state.messages.append(Message(role="assistant", content=raw_response))
                state.messages.append(Message(
                    role="user",
                    content=(
                        "Your previous reply had no tool call. Reply again "
                        "with a JSON object containing an `action` — either a "
                        "real tool call or `done_gathering` if you are done."
                    ),
                ))
                # Stay in GATHERING, will re-enter this handler
                return state
            state.gathering_exit_reason = "model_emitted_thought_only_twice"
            logger.warning(
                "Step %d: model gave no action twice in a row; exiting gathering",
                state.next_step_number,
            )
            state.phase = Phase.COMPILING
            return state

        state.null_action_reprompted = False

        # Persist the step
        kind = "signal" if signal_done else None
        step = InvestigationStep(state.next_step_number, thought, action, observation, kind=kind)
        state.processed_steps.append(step)

        if deps.store:
            await deps.store.add_step(
                investigation_id=state.investigation_id,
                step_number=state.next_step_number,
                thought=thought.content,
                action=_asdict(action.tool_call) if action else None,
                observation=_asdict(observation.tool_result) if observation else None,
                kind=kind,
            )

        if deps.on_step:
            await deps.on_step(step)

        state.next_step_number += 1

        if signal_done:
            await _auto_fill_unchecked_services(state, deps)
            state.phase = Phase.COMPILING
            return state

        state.actions_taken += 1
        state.action_steps_since_reflection += 1

        # Stall detection
        if state.consecutive_empty_tool_calls >= 2:
            state.gathering_exit_reason = "stalled_no_new_evidence"
            logger.info(
                "Exiting gathering early: %d consecutive tool calls returned no new chunks",
                state.consecutive_empty_tool_calls,
            )
            await _auto_fill_unchecked_services(state, deps)
            state.phase = Phase.COMPILING
            return state

        state.messages.append(Message(role="assistant", content=raw_response))
        if observation and observation.tool_result:
            res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
            prefix = "(repeat call — returning cached result)\n" if is_repeat_call else ""
            state.messages.append(Message(role="user", content=f"{prefix}Observation:\n{_compact_observation(res)}"))

        if state.tool_call_ledger:
            state.messages[0] = Message(
                role="system",
                content=_build_system_prompt(deps.known_services) + "\n\n" + _ledger_summary(state.tool_call_ledger),
            )

    except Exception as e:
        logger.error(f"Step {state.next_step_number} failed during processing: {e}")
        if state.messages and state.messages[-1].role == "assistant":
            state.messages.pop()

    # Stay in GATHERING for next iteration
    return state


async def handle_compiling(state: InvestigationState, deps: LoopDeps) -> InvestigationState:
    chunks_obj = await deps.store.get_chunks(state.investigation_id) if deps.store else []
    evidence_chunks = [
        {
            "chunk_id": c.chunk_id,
            "service": c.service,
            "timestamp": str(c.timestamp),
            "message": c.message,
        }
        for c in chunks_obj
    ]

    if deps.on_phase_change:
        try:
            await deps.on_phase_change("compiling")
        except Exception:
            logger.debug("on_phase_change(compiling) hook raised", exc_info=True)

    recent_thoughts = [
        s.thought.content for s in state.processed_steps[-4:] if s.thought and s.thought.content
    ]

    try:
        compile_result = await compile_answer(
            llm=deps.llm,
            query=state.query,
            resolved_intent=state.resolved_intent,
            evidence=evidence_chunks,
            tool_ledger=state.tool_call_ledger,
            recent_thoughts=recent_thoughts,
            known_services=deps.known_services,
        )
        final_answer_dict = compile_result.answer
        compile_source = compile_result.source
        compile_attempts = compile_result.attempts
        floor_adjustments = compile_result.floor_adjustments
    except Exception as e:
        logger.error("Compiler raised; falling back to deterministic synth: %s", e)
        final_answer_dict = synthesize_answer(
            query=state.query,
            resolved_intent=state.resolved_intent,
            evidence=evidence_chunks,
            tool_ledger=state.tool_call_ledger,
            extra_gaps=[f"compile_answer raised: {e}"],
        )
        compile_source = "deterministic_exception"
        compile_attempts = 0
        floor_adjustments = []

    compile_thought = (
        f"Compiled answer from {len(evidence_chunks)} evidence chunks across "
        f"{len({c.get('service') for c in evidence_chunks if c.get('service')})} services "
        f"(source={compile_source}, attempts={compile_attempts}, "
        f"exit_reason={state.gathering_exit_reason})"
    )
    compile_step = InvestigationStep(
        state.next_step_number,
        Thought(compile_thought),
        None,
        None,
        kind="compile",
    )
    state.processed_steps.append(compile_step)
    if deps.store:
        await deps.store.add_step(
            investigation_id=state.investigation_id,
            step_number=state.next_step_number,
            thought=compile_thought,
            action=None,
            observation=None,
            kind="compile",
        )
    if deps.on_step:
        await deps.on_step(compile_step)

    if deps.store:
        await deps.store.finalize(state.investigation_id, json.dumps(final_answer_dict))

    state._compile_result = {
        "final_answer_dict": final_answer_dict,
        "compile_source": compile_source,
        "compile_attempts": compile_attempts,
        "floor_adjustments": floor_adjustments,
        "evidence_chunks": evidence_chunks,
        "chunks_obj": chunks_obj,
    }

    if deps.on_phase_change:
        try:
            await deps.on_phase_change("done")
        except Exception:
            logger.debug("on_phase_change(done) hook raised", exc_info=True)

    state.phase = Phase.DONE
    return state


# ─── Phase dispatch table ────────────────────────────────────────────────────
#
# GATHERING ⇄ REFLECTING is a cycle, not a pipeline. ReAct is preserved:
# each gathering step is act→observe, reflection is the guard that decides
# whether to loop back (probe somewhere new) or exit to COMPILING. The FSM
# is a supervisor around the loop, not a replacement for it.

HANDLERS: dict[Phase, Callable] = {
    Phase.RESOLVING: handle_resolving,
    Phase.SWEEPING: handle_sweeping,
    Phase.GATHERING: handle_gathering,
    Phase.REFLECTING: handle_reflecting,
    Phase.COMPILING: handle_compiling,
    Phase.WAITING_CLARIFICATION: handle_waiting_clarification,
}


# ─── Main class (preserves public interface) ─────────────────────────────────

class ReactInvestigationLoop:
    # Expose compaction constants on the class for tests that reference them.
    MAX_OBS_ITEMS = MAX_OBS_ITEMS
    MAX_OBS_TEXT_CHARS = MAX_OBS_TEXT_CHARS
    MAX_OBS_TOTAL_CHARS = MAX_OBS_TOTAL_CHARS

    def __init__(
        self,
        llm: LLMProvider,
        tools: dict[str, Callable],
        known_services: list[str],
        pool: Optional[asyncpg.Pool] = None,
        store: Optional[InvestigationStore] = None,
        max_iterations: int = 10,
        min_gathering_actions: int = 3,
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
        self.max_iterations = max_iterations
        self.min_gathering_actions = min_gathering_actions
        self.min_iteration_delay = min_iteration_delay
        self.store = store
        self.enable_reflection = enable_reflection
        self.reflection_interval = reflection_interval
        self.max_reflections = max_reflections
        self.llm_max_calls_per_min = llm_max_calls_per_min
        self._llm_call_timestamps: list[float] = []

    # Keep these as class/instance methods for backwards compat with tests.
    @staticmethod
    def _ledger_key(tool_name: str, args: dict) -> str:
        return _ledger_key(tool_name, args)

    @staticmethod
    def _ledger_summary(ledger: dict[str, dict]) -> str:
        return _ledger_summary(ledger)

    async def _wait_for_rate_limit(self):
        deps = LoopDeps(
            llm=self.llm, tools=self.tools, known_services=self.known_services,
            pool=self.pool, store=self.store,
            llm_call_timestamps=self._llm_call_timestamps,
            llm_max_calls_per_min=self.llm_max_calls_per_min,
        )
        await _wait_for_rate_limit(deps)
        self._llm_call_timestamps = deps.llm_call_timestamps

    @classmethod
    def _compact_observation(cls, result: Any) -> str:
        return _compact_observation(result)

    def _extract_chunks(self, tool_result: Any) -> list[dict]:
        return _extract_chunks(tool_result)

    def _build_system_prompt(self) -> str:
        return _build_system_prompt(self.known_services)

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

        # --- Persistence: Resume or Create ---
        investigation_obj = None
        if self.store:
            if investigation_id:
                investigation_obj = await self.store.get_by_id(investigation_id)
            elif resume:
                investigation_obj = await self.store.get_or_create(query)
            else:
                investigation_obj = await self.store.create(query)

        # --- Try to resume from serialized state ---
        state = None
        if investigation_obj and hasattr(investigation_obj, 'state_json') and investigation_obj.state_json:
            try:
                state = InvestigationState.from_json(json.dumps(investigation_obj.state_json))
                logger.info(f"Resumed investigation {investigation_obj.id} from phase {state.phase.value}")
                # Kick WAITING_CLARIFICATION into the resume path so the
                # dispatch loop doesn't exit immediately.
                if state.phase == Phase.WAITING_CLARIFICATION:
                    state.post_clarification = True
                    state.pending_question = None
                    state.phase = Phase.RESOLVING
            except Exception as e:
                logger.warning(f"Failed to restore state from state_json, falling back: {e}")
                state = None

        # --- Fall back to legacy resume (replay from steps) ---
        if state is None:
            existing_steps = await self.store.get_steps(investigation_obj.id) if self.store else []

            post_clarification = False
            if existing_steps:
                last_step = existing_steps[-1]
                if last_step.action and (
                    last_step.action.get("name") == "ask_user"
                    or last_step.action.get("tool") == "ask_user"
                ):
                    if last_step.observation and last_step.observation.get("result"):
                        post_clarification = True

            inv_id = investigation_obj.id if investigation_obj else UUID("00000000-0000-0000-0000-000000000000")

            if existing_steps and not post_clarification:
                # Reconstruct state from existing steps (legacy resume path)
                state = InvestigationState(
                    phase=Phase.GATHERING,
                    investigation_id=inv_id,
                    query=query,
                    messages=[
                        Message(role="system", content=_build_system_prompt(self.known_services)),
                        Message(role="user", content=query),
                    ],
                    tool_call_ledger={},
                )

                for s in existing_steps:
                    thought = Thought(content=s.thought)
                    action = None
                    observation = None

                    if s.action:
                        action = Action(tool_call=ToolCall(
                            name=s.action.get("name") or s.action.get("tool"),
                            args=s.action["args"],
                        ))
                    if s.observation:
                        observation = Observation(tool_result=ToolResult(
                            tool_name=s.observation.get("tool_name", "unknown"),
                            args=s.observation.get("args", {}),
                            result=s.observation.get("result"),
                            error=s.observation.get("error"),
                        ))

                    step = InvestigationStep(
                        s.step_number, thought, action, observation,
                        s.created_at,
                        kind=getattr(s, "kind", None),
                    )
                    state.processed_steps.append(step)

                    llm_payload = {"thought": s.thought}
                    if action:
                        llm_payload["action"] = {"tool": action.tool_call.name, "args": action.tool_call.args}
                    state.messages.append(Message(role="assistant", content=json.dumps(llm_payload)))
                    if observation:
                        res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                        state.messages.append(Message(role="user", content=f"Observation:\n{_compact_observation(res)}"))

                    if action and observation and observation.tool_result.result is not None:
                        lkey = _ledger_key(action.tool_call.name, action.tool_call.args)
                        state.tool_call_ledger.setdefault(lkey, {
                            "tool_name": action.tool_call.name,
                            "args": action.tool_call.args,
                            "result": observation.tool_result.result,
                        })

                    state.next_step_number = max(state.next_step_number, s.step_number + 1)

                # Reconstruct counters
                for s in existing_steps:
                    if getattr(s, "kind", None) == "reflection":
                        state.action_steps_since_reflection = 0
                        state.reflections_used += 1
                    elif getattr(s, "kind", None) is None and s.action:
                        state.action_steps_since_reflection += 1
            else:
                # Fresh investigation or post-clarification
                state = InvestigationState(
                    phase=Phase.RESOLVING,
                    investigation_id=inv_id,
                    query=query,
                    messages=[],
                    tool_call_ledger={},
                    post_clarification=post_clarification,
                )

        # --- Build LoopDeps ---
        deps = LoopDeps(
            llm=self.llm,
            tools=self.tools,
            known_services=self.known_services,
            pool=self.pool,
            store=self.store,
            max_iterations=self.max_iterations,
            min_gathering_actions=self.min_gathering_actions,
            min_iteration_delay=self.min_iteration_delay,
            enable_reflection=self.enable_reflection,
            reflection_interval=self.reflection_interval,
            max_reflections=self.max_reflections,
            llm_max_calls_per_min=self.llm_max_calls_per_min,
            on_step=on_step,
            on_phase_change=on_phase_change,
            llm_call_timestamps=self._llm_call_timestamps,
        )

        # --- Dispatch loop ---
        while state.phase not in (Phase.DONE, Phase.WAITING_CLARIFICATION):
            handler = HANDLERS[state.phase]
            state = await handler(state, deps)

            # Persist state snapshot after each transition
            if self.store and investigation_obj:
                try:
                    investigation_obj.state_json = json.loads(state.to_json())
                    self.store.session.add(investigation_obj)
                    await self.store.session.commit()
                except Exception as e:
                    logger.debug(f"Failed to persist state_json: {e}")

        self._llm_call_timestamps = deps.llm_call_timestamps

        # --- Return result ---
        if state.phase == Phase.WAITING_CLARIFICATION:
            return InvestigationResult(
                id=str(state.investigation_id),
                query=query,
                steps=state.processed_steps,
                answer="Awaiting clarification...",
                evidence_chunk_ids=[],
                confidence="low",
                duration_seconds=time.time() - start_time,
            )

        cr = getattr(state, "_compile_result", {})
        final_answer_dict = cr.get("final_answer_dict", {})
        chunks_obj = cr.get("chunks_obj", [])

        stats = {
            "iterations_used": state.actions_taken,
            "reflections_used": state.reflections_used,
            "chunks_gathered": len(cr.get("evidence_chunks", [])),
            "tools_called": sorted({e["tool_name"] for e in state.tool_call_ledger.values()}),
            "compile_source": cr.get("compile_source", "unknown"),
            "compile_attempts": cr.get("compile_attempts", 0),
            "floor_adjustments": cr.get("floor_adjustments", []),
            "gathering_exit_reason": state.gathering_exit_reason,
        }

        return InvestigationResult(
            id=str(state.investigation_id),
            query=query,
            steps=state.processed_steps,
            answer=json.dumps(final_answer_dict, indent=2),
            evidence_chunk_ids=[c.chunk_id for c in chunks_obj],
            confidence=final_answer_dict.get("confidence", "low"),
            duration_seconds=time.time() - start_time,
            evidence=cr.get("evidence_chunks", []),
            stats=stats,
        )


def _asdict(obj):
    from dataclasses import asdict as _asdict_fn
    return _asdict_fn(obj)
