from __future__ import annotations
import json
import logging
import asyncio
import time
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from repi.llm.provider import LLMProvider, Message
from repi.investigation.tools import ToolCall, ToolResult, TOOL_SCHEMAS
from repi.retrieval.heuristics import extract_time_range, progressive_search, cluster_logs
from repi.investigation.store import InvestigationStore

logger = logging.getLogger(__name__)

def parse_llm_response(raw: str) -> dict:
    """Extract and parse JSON from LLM response, supporting multiple blocks and markdown fences."""
    cleaned = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    objects = _extract_json_objects(cleaned)
    if not objects:
        raise ValueError(f"No valid JSON found in LLM response: {raw[:200]}")
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
    timestamp: datetime = field(default_factory=datetime.utcnow)

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
        store: Optional[InvestigationStore] = None,
        max_iterations: int = 10,
        min_iteration_delay: float = 2.0,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.known_services = known_services
        self.max_iterations = max_iterations
        self.min_iteration_delay = min_iteration_delay
        self.store = store
        self._llm_call_timestamps: list[float] = []

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
        chunks = []
        if isinstance(tool_result, list):
            for item in tool_result:
                if isinstance(item, dict) and "chunk_id" in item:
                    chunks.append(item)
        elif isinstance(tool_result, dict):
            if "chunk_id" in tool_result:
                chunks.append(tool_result)
        return chunks

    async def investigate(
        self,
        query: str,
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
            if resume:
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
        
        messages = [
            Message(role="system", content=self._build_system_prompt()),
            Message(role="user", content=query)
        ]

        # Reconstruct state from existing steps
        processed_steps = []
        start_at_iteration = 0
        
        for s in existing_steps:
            # Reconstruct Step objects for the result
            thought = Thought(content=s.thought)
            action = None
            observation = None
            
            if s.action:
                # Store used 'name' from ToolCall dataclass asdict
                action = Action(tool_call=ToolCall(name=s.action.get("name") or s.action.get("tool"), args=s.action["args"]))
            if s.observation:
                observation = Observation(tool_result=ToolResult(
                    tool_name=s.observation.get("tool_name", "unknown"),
                    args=s.observation.get("args", {}),
                    result=s.observation.get("result"),
                    error=s.observation.get("error")
                ))
            
            step = InvestigationStep(s.step_number, thought, action, observation, s.created_at)
            processed_steps.append(step)
            
            # Reconstruct messages for LLM context
            llm_payload = {"thought": s.thought}
            if action:
                llm_payload["action"] = {"tool": action.tool_call.name, "args": action.tool_call.args}
            
            messages.append(Message(role="assistant", content=json.dumps(llm_payload)))
            if observation:
                res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                messages.append(Message(role="user", content=f"Observation:\n{json.dumps(res, default=str)}"))
            
            start_at_iteration = max(start_at_iteration, s.step_number)

        # Pre-investigation if starting fresh
        if not processed_steps:
            now = datetime.utcnow()
            time_hint = extract_time_range(query, now)
            if time_hint and "search_logs" in self.tools:
                initial_logs = await self.tools["search_logs"](
                    query="error OR timeout OR failure OR exception",
                    time_from=time_hint[0].isoformat(),
                    time_to=time_hint[1].isoformat(),
                    top_k=15
                )
                if initial_logs:
                    clustered = cluster_logs(initial_logs)
                    obs_text = json.dumps(clustered, indent=2, default=str)
                    msg_content = f"PRE-INVESTIGATION SIGNAL FOUND:\n{obs_text}"
                    messages.append(Message(role="user", content=msg_content))
                    # Store evidence
                    if self.store:
                        await self.store.add_chunks(investigation_obj.id, initial_logs)
                        # Refresh evidence_chunks
                        chunks_obj = await self.store.get_chunks(investigation_obj.id)
                        evidence_chunks = [{"chunk_id": c.chunk_id, "text": c.message} for c in chunks_obj]

        final_answer_dict = {}
        
        for i in range(start_at_iteration, self.max_iterations):
            if i > start_at_iteration:
                await asyncio.sleep(self.min_iteration_delay)
            
            try:
                await self._wait_for_rate_limit()
                if self.store: await self.store.increment_llm_calls(investigation_obj.id)
                
                raw_response = await self.llm.complete(messages)
                parsed = parse_llm_response(raw_response)
                
                thought = Thought(content=parsed.get("thought", ""))
                action = None
                observation = None
                
                if "action" in parsed:
                    tool_name = parsed["action"].get("tool")
                    tool_args = parsed["action"].get("args", {})
                    
                    # Handle LLM occasionally trying to use a 'final_answer' tool
                    if tool_name == "final_answer":
                        final_answer_dict = tool_args or {"summary": thought.content}
                        if self.store:
                            await self.store.finalize(investigation_obj.id, json.dumps(final_answer_dict))
                        break

                    action = Action(tool_call=ToolCall(name=tool_name, args=tool_args))
                    
                    if tool_name in self.tools:
                        try:
                            result = await self.tools[tool_name](**tool_args)
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name,
                                args=tool_args,
                                result=result
                            ))
                            # Persistence
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
                    
                step = InvestigationStep(i + 1, thought, action, observation)
                processed_steps.append(step)
                
                # Persistence: Store Step
                if self.store:
                    await self.store.add_step(
                        investigation_id=investigation_obj.id,
                        step_number=i + 1,
                        thought=thought.content,
                        action=asdict(action.tool_call) if action else None,
                        observation=asdict(observation.tool_result) if observation else None
                    )

                if on_step: await on_step(step)
                
                if "answer" in parsed:
                    final_answer_dict = parsed["answer"]
                    if self.store:
                        await self.store.finalize(investigation_obj.id, json.dumps(final_answer_dict))
                    break
                
                messages.append(Message(role="assistant", content=raw_response))
                if observation and observation.tool_result:
                    res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                    messages.append(Message(role="user", content=f"Observation:\n{json.dumps(res, default=str)}"))
                
            except Exception as e:
                logger.error(f"Iteration {i+1} failed: {e}")
                messages.append(Message(role="user", content=f"Internal error: {str(e)}. Please retry or summarize."))

        # Final Ans Enhancement from DB evidence if available
        if self.store:
            chunks_obj = await self.store.get_chunks(investigation_obj.id)
            evidence_chunks = [{"service": c.service, "timestamp": c.timestamp, "message": c.message} for c in chunks_obj]

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

RULES:
1. ALWAYS identify root cause and correlate logs cross-service.
2. NEVER assume missing logs = failure. Expand time/query.
3. Every claim MUST be backed by logs in 'evidence'.
4. Ground your conclusion in investigation_chunks.

FORMAT:
Tool Call: {{ "thought": "...", "action": {{ "tool": "...", "args": {{...}} }} }}
Final Answer: {{ "thought": "...", "answer": {{ "summary": "...", "root_cause": "...", "evidence": [...], "confidence": "..." }} }}

Current UTC: {datetime.utcnow().isoformat()}
"""

def asdict(obj):
    from dataclasses import asdict as _asdict
    return _asdict(obj)
