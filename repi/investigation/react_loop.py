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
from repi.llm.provider import LLMProvider, Message
from repi.investigation.tools import ToolCall, ToolResult, TOOL_SCHEMAS
from repi.retrieval.heuristics import cluster_logs
from repi.investigation.store import InvestigationStore
from repi.intent.resolver import resolve as resolve_intent, ResolvedIntent, ClarificationNeeded
from repi.investigation.sweep import auto_sweep
from repi.investigation.schema import InvestigationAnswer, validate_answer

logger = logging.getLogger(__name__)


# Reflection turn injected every N action steps. The LLM is asked to step back,
# summarize hypotheses + evidence, and pick the highest-value next action.
# Pure thought — no tool call expected on this turn.
#
# Deliberately does NOT invite early termination. An earlier draft included a
# "give up and submit with low confidence if you want" bullet; in practice the
# LLM read that as permission to bail after the first weak scan on noisy
# datasets. Termination is now gated explicitly: only after multiple distinct
# lines of inquiry have all returned no useful evidence.
REFLECTION_PROMPT = (
    "Stop. Before your next action, reflect:\n"
    "1. What hypotheses have you considered so far?\n"
    "2. What evidence supports or refutes each hypothesis?\n"
    "3. What is the single highest-value next action — and why?\n"
    "4. Termination check: ONLY if you have already pursued multiple distinct\n"
    "   lines of inquiry (e.g. different time windows, different services,\n"
    "   different log levels) AND each returned no useful evidence, you may\n"
    "   submit with low confidence. Otherwise CONTINUE investigating — a\n"
    "   single weak scan is not grounds for giving up.\n"
    "Reply with JSON of the form {\"thought\": \"...\"} containing your reflection. "
    "Do NOT issue a tool call on this turn."
)

def _strip_js_comments(text: str) -> str:
    """Remove /* block comments */ and // line comments from JSON-like text.
    Only strips // when it starts a line (after optional whitespace) to avoid
    corrupting URLs like http:// inside string values."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//[^\n]*", "", text, flags=re.MULTILINE)
    return text


def parse_llm_response(raw: str) -> dict:
    """Extract and parse JSON from LLM response, supporting multiple blocks and markdown fences."""
    # Remove markdown fences
    cleaned = re.sub(r"```json|```", "", raw).strip()

    # Remove common prefixes like "Tool Call:" or "Final Answer:"
    cleaned = re.sub(r"^(?:Tool Call|Final Answer):\s*", "", cleaned, flags=re.IGNORECASE)

    # Strip JS-style comments that LLMs sometimes emit
    cleaned = _strip_js_comments(cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    objects = _extract_json_objects(cleaned)
    if not objects:
        logger.error(f"Failed to parse JSON from LLM response. Raw length: {len(raw)}. Raw content: {raw}")
        raise ValueError(f"No valid JSON found in LLM response. Check logs for full content.")
    
    if len(objects) == 1:
        return objects[0]
    
    merged = {}
    for obj in objects:
        merged.update(obj)
    return merged


def _extract_json_objects(text: str) -> list[dict]:
    objects = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start:i+1]
                try:
                    objects.append(json.loads(candidate))
                except json.JSONDecodeError:
                    pass
                start = None
    return objects


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
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.known_services = known_services
        self.pool = pool
        self.max_iterations = max_iterations
        self.min_iteration_delay = min_iteration_delay
        self.store = store
        self.enable_reflection = enable_reflection
        self.reflection_interval = reflection_interval
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
        while len(self._llm_call_timestamps) >= 3:
            wait_time = 60 - (now - self._llm_call_timestamps[0]) + 1
            logger.warning(f"Rate limit: Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            now = time.time()
            self._llm_call_timestamps = [t for t in self._llm_call_timestamps if now - t < 60]
        self._llm_call_timestamps.append(now)

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
        # `tool_call_ledger` (issue #11) dedupes identical tool invocations across
        # iterations: hash → {tool_name, args, result}. The summary is appended to
        # the system message each turn so the LLM knows what's already been tried.
        tool_call_ledger: dict[str, dict] = {}

        messages = [
            Message(role="system", content=self._build_system_prompt()),
            Message(role="user", content=query)
        ]

        if resolved_intent and self.pool and (not existing_steps or post_clarification):
            sweep_results = await auto_sweep(
                pool=self.pool,
                time_from=resolved_intent.time_from,
                time_to=resolved_intent.time_to,
                exclude_services=[]
            )

            sweep_msg = f"SWEEP CONTEXT:\n{json.dumps(sweep_results, indent=2)}\n\n"
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
                messages.append(Message(role="user", content=f"Observation:\n{json.dumps(res, default=str)}"))

            # Seed the ledger from replayed steps so dedupe survives resume.
            if action and observation and observation.tool_result.result is not None:
                ledger_key = self._ledger_key(action.tool_call.name, action.tool_call.args)
                tool_call_ledger.setdefault(ledger_key, {
                    "tool_name": action.tool_call.name,
                    "args": action.tool_call.args,
                    "result": observation.tool_result.result,
                })

            start_at_iteration = max(start_at_iteration, s.step_number)

        final_answer_dict = {}
        validation_retries = 0

        # Count action steps since the last reflection so we can inject the
        # forced re-plan every `reflection_interval` iterations. Replayed steps
        # from a resumed investigation contribute to the count (reflections in
        # the existing trace reset it) so resume doesn't immediately re-reflect.
        action_steps_since_reflection = 0
        for s in existing_steps:
            if getattr(s, "kind", None) == "reflection":
                action_steps_since_reflection = 0
            else:
                action_steps_since_reflection += 1

        for i in range(start_at_iteration, self.max_iterations):
            if i > start_at_iteration:
                await asyncio.sleep(self.min_iteration_delay)

            # --- Reflection turn ------------------------------------------------
            if (
                self.enable_reflection
                and self.reflection_interval > 0
                and action_steps_since_reflection >= self.reflection_interval
            ):
                messages.append(Message(role="user", content=REFLECTION_PROMPT))
                try:
                    await self._wait_for_rate_limit()
                    if self.store and investigation_obj:
                        await self.store.increment_llm_calls(investigation_obj.id)
                    raw_reflection = await self.llm.complete(messages)
                except Exception as e:
                    logger.error(f"Reflection iteration {i+1} failed: {e}")
                    # Roll back the just-appended REFLECTION_PROMPT so the next
                    # iteration doesn't see a dangling user turn with no assistant
                    # reply — that would confuse the model on retry.
                    if messages and messages[-1].content == REFLECTION_PROMPT:
                        messages.pop()
                    action_steps_since_reflection = 0
                    continue

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
                    i + 1,
                    Thought(reflection_thought),
                    None,
                    None,
                    kind="reflection",
                )
                processed_steps.append(reflection_step)

                if self.store and investigation_obj:
                    await self.store.add_step(
                        investigation_id=investigation_obj.id,
                        step_number=i + 1,
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

                action_steps_since_reflection = 0
                continue

            try:
                await self._wait_for_rate_limit()
                if self.store: await self.store.increment_llm_calls(investigation_obj.id)

                raw_response = await self.llm.complete(messages)
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
                
                is_repeat_call = False
                if "action" in parsed:
                    tool_name = parsed["action"].get("tool")
                    tool_args = parsed["action"].get("args", {})

                    if tool_name in ["Final Answer", "FinalAnswer", "submit", "finish", "submit_answer"]:
                        parsed["answer"] = tool_args
                    else:
                        action = Action(tool_call=ToolCall(name=tool_name, args=tool_args))

                        if tool_name in self.tools:
                            ledger_key = self._ledger_key(tool_name, tool_args)
                            cached = tool_call_ledger.get(ledger_key)
                            if cached is not None:
                                # Repeat call — short-circuit without invoking the tool.
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
                                    if self.store:
                                        new_chunks = self._extract_chunks(result)
                                        await self.store.add_chunks(investigation_obj.id, new_chunks)
                                except Exception as e:
                                    logger.error(f"Tool failed: {e}")
                                    observation = Observation(tool_result=ToolResult(
                                        tool_name=tool_name, args=tool_args, result=None, error=str(e)
                                    ))
                        else:
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name, args=tool_args, result=None, error=f"Unknown tool '{tool_name}'"
                            ))
                    
                if action or thought.content:
                    step = InvestigationStep(i + 1, thought, action, observation)
                    processed_steps.append(step)
                    action_steps_since_reflection += 1

                    if self.store:
                        await self.store.add_step(
                            investigation_id=investigation_obj.id,
                            step_number=i + 1,
                            thought=thought.content,
                            action=asdict(action.tool_call) if action else None,
                            observation=asdict(observation.tool_result) if observation else None,
                            kind=None,
                        )

                    if on_step: await on_step(step)
                
                if "answer" in parsed:
                    ans_dict = parsed["answer"]

                    chunks_obj = await self.store.get_chunks(investigation_obj.id) if self.store else []
                    evidence_ids = {c.chunk_id for c in chunks_obj}
                    
                    is_valid, errors = validate_answer(ans_dict, evidence_ids)
                    
                    if not is_valid and validation_retries < 1:
                        validation_retries += 1
                        error_msg = f"VALIDATION ERROR: Your final answer did not match the required schema or references missing chunk_ids.\nErrors: {errors}\nPlease correct the final answer and try again."
                        messages.append(Message(role="user", content=error_msg))
                        continue
                    
                    if not is_valid:
                        ans_dict["confidence"] = "low"
                        ans_dict.setdefault("gaps", []).append(f"Schema validation failed: {errors}")
                    
                    final_answer_dict = ans_dict
                    if self.store:
                        await self.store.finalize(investigation_obj.id, json.dumps(final_answer_dict))
                    break
                
                messages.append(Message(role="assistant", content=raw_response))
                if observation and observation.tool_result:
                    res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                    prefix = "(repeat call — returning cached result)\n" if is_repeat_call else ""
                    messages.append(Message(role="user", content=f"{prefix}Observation:\n{json.dumps(res, default=str)}"))

                # Refresh the system prompt with the current ledger so the next
                # turn's LLM call sees an up-to-date "already tried" view.
                if tool_call_ledger:
                    messages[0] = Message(
                        role="system",
                        content=self._build_system_prompt() + "\n\n" + self._ledger_summary(tool_call_ledger),
                    )
                
            except Exception as e:
                logger.error(f"Iteration {i+1} failed: {e}")
                messages.append(Message(role="user", content=f"Internal error: {str(e)}. Please retry or summarize."))

        if self.store:
            chunks_obj = await self.store.get_chunks(investigation_obj.id)
            evidence_chunks = [{"service": c.service, "timestamp": c.timestamp, "message": c.message} for c in chunks_obj]

        # Defensive fallback: if the loop exited without a finalized answer
        # (max iterations reached, repeated parse failures, etc.) emit a
        # low-confidence stub instead of an empty {} so downstream consumers
        # always see a valid shape with explicit gaps.
        if not final_answer_dict:
            final_answer_dict = {
                "incident_window": {},
                "affected_services": [],
                "trigger_event": {},
                "propagation_chain": [],
                "root_cause": "unable_to_determine — investigation exited without a finalized answer",
                "ruled_out_hypotheses": [],
                "assumptions": [],
                "confidence": "low",
                "gaps": [
                    "ReAct loop exhausted max_iterations without submitting an answer — "
                    "no data may have been found in the resolved time window, or the LLM "
                    "looped on tool calls without converging."
                ],
            }
            if self.store and investigation_obj:
                await self.store.finalize(investigation_obj.id, json.dumps(final_answer_dict))

        return InvestigationResult(
            id=str(investigation_obj.id) if investigation_obj else "unknown",
            query=query,
            steps=processed_steps,
            answer=json.dumps(final_answer_dict, indent=2),
            evidence_chunk_ids=[c.chunk_id for c in chunks_obj] if self.store else [],
            confidence=final_answer_dict.get("confidence", "low"),
            duration_seconds=time.time() - start_time,
            evidence=evidence_chunks
        )

    def _build_system_prompt(self) -> str:
        return f"""You are a senior SRE. Postgres is the source of truth for this investigation.

KNOWN SERVICES: {self.known_services}
TOOLS: {json.dumps(TOOL_SCHEMAS, indent=2)}

GOAL: Identify the root cause of the reported issue using evidence from logs.

FORMAT:
Tool Call: {{ "thought": "...", "action": {{ "tool": "...", "args": {{...}} }} }}
Final Answer: {{ "thought": "...", "answer": <InvestigationAnswer> }}

<InvestigationAnswer> Schema:
{{
  "incident_window": {{"start": "ISO8601", "end": "ISO8601"}},
  "affected_services": ["service-a", "service-b"],
  "trigger_event": {{"chunk_id": "uuid", "service": "...", "timestamp": "...", "log_line": "..."}},
  "propagation_chain": [
    {{"service": "...", "chunk_id": "...", "ts": "...", "what": "..."}}
  ],
  "root_cause": "one-sentence verdict",
  "ruled_out_hypotheses": [
    {{"hypothesis": "...", "why_ruled_out": "..."}}
  ],
  "assumptions": ["e.g. assumed 'Friday night' = ..."],
  "confidence": "high | medium | low",
  "gaps": ["missing logs for service-x", ...]
}}

CRITICAL RULES:
1. Every chunk_id used in trigger_event or propagation_chain MUST have been retrieved by a tool first.
2. ALWAYS correlate logs cross-service. Use scan_window.
3. If confidence is not 'high', you MUST explain what is missing in 'gaps'.
4. Do not hand-wave. Citing specific log lines and chunk_ids is mandatory.
5. `ruled_out_hypotheses` MUST explicitly name every known service that appeared in scan_window/auto_sweep but is NOT in your `affected_services` — give a one-line rationale per service (e.g. "no errors in this window", "only downstream symptom", "coincidental but causally unrelated"). Generic hypotheses like "network outage" are not a substitute.
6. `root_cause` MUST describe the FULL mechanism end-to-end, not just the trigger. Include the cascade chain (e.g. retry storm, pool exhaustion, key-distribution failure) so a reader understands WHY the trigger produced the user-visible symptom.
7. If your tool calls return no data in the resolved time window, do NOT return an empty answer. Still call submit_answer with confidence='low' and put "no logs found in the resolved time window — possible misalignment between query phrasing and seeded data" in `gaps`.

Current UTC: {_dh.to_iso(_dh.now())}
"""

def asdict(obj):
    from dataclasses import asdict as _asdict
    return _asdict(obj)
