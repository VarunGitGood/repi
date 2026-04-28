from __future__ import annotations
import json
import logging
import asyncio
import time
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from src.app.llm.provider import LLMProvider, Message
from src.app.investigation.tools import ToolCall, ToolResult, TOOL_SCHEMAS
from src.app.retrieval.heuristics import extract_time_range, progressive_search, cluster_logs

logger = logging.getLogger(__name__)

def parse_llm_response(raw: str) -> dict:
    """Extract and parse JSON from LLM response, supporting multiple blocks and markdown fences."""
    # Step 1: strip markdown fences
    cleaned = re.sub(r"```json|```", "", raw).strip()

    # Step 2: try parsing as a single object first (happy path)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Step 3: find ALL JSON objects in the response using brace matching
    objects = _extract_json_objects(cleaned)

    if not objects:
        raise ValueError(f"No valid JSON found in LLM response: {raw[:200]}")

    if len(objects) == 1:
        return objects[0]

    # Step 4: merge multiple objects — last one wins per key
    merged = {}
    for obj in objects:
        merged.update(obj)
    return merged


def _extract_json_objects(text: str) -> list[dict]:
    """Extract all top-level JSON objects from text using brace counting."""
    objects = []
    depth = 0
    start = None

    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
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
        max_iterations: int = 10,
        min_iteration_delay: float = 2.0,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.known_services = known_services
        self.max_iterations = max_iterations
        self.min_iteration_delay = min_iteration_delay
        self._tool_failure_counts: dict[str, int] = {}
        self._evidence_chunk_ids: set[str] = set()
        self._evidence_chunks: list[dict] = []
        self._llm_call_timestamps: list[float] = []

    async def _wait_for_rate_limit(self):
        """Enforce a rolling window of max 3 calls per 60 seconds."""
        now = time.time()
        self._llm_call_timestamps = [t for t in self._llm_call_timestamps if now - t < 60]
        
        while len(self._llm_call_timestamps) >= 3:
            wait_time = 60 - (now - self._llm_call_timestamps[0]) + 1
            logger.warning(f"Rate limit management: 3 calls already made in 60s. Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)
            now = time.time()
            self._llm_call_timestamps = [t for t in self._llm_call_timestamps if now - t < 60]
        
        self._llm_call_timestamps.append(now)

    def _extract_chunks(self, tool_result: Any) -> list[dict]:
        """Extract full chunk dictionaries from tool results."""
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
    ) -> InvestigationResult:
        if known_services:
            self.known_services = known_services

        start_time = time.time()
        self._tool_failure_counts = {}
        self._evidence_chunk_ids = set()
        self._evidence_chunks = []
        self._llm_call_timestamps = []
        
        messages = [
            Message(role="system", content=self._build_system_prompt()),
            Message(role="user", content=query)
        ]
        
        # --- PRE-INVESTIGATION: TIME-AWARE DISCOVERY ---
        now = datetime.utcnow()
        time_hint = extract_time_range(query, now)
        initial_logs = []
        
        if time_hint:
            logger.info(f"Explicit time hint found in query: {time_hint}")
            if "search_logs" in self.tools:
                # search_logs(query, service, time_from, time_to, top_k)
                initial_logs = await self.tools["search_logs"](
                    query="error OR timeout OR failure OR exception",
                    time_from=time_hint[0].isoformat(),
                    time_to=time_hint[1].isoformat(),
                    top_k=15
                )

        if not initial_logs and "search_logs" in self.tools:
            # Fallback to heuristics (can't use progressive_search directly here as it needs RRFRetrievalService instance,
            # but we can do a simplified version here or hope LLM does it via tools)
            pass
        
        if initial_logs:
            # Cluster and inject as a starting observation
            clustered = cluster_logs(initial_logs)
            if clustered:
                obs_text = json.dumps(clustered, indent=2, default=str)
                messages.append(Message(role="user", content=f"PRE-INVESTIGATION SIGNAL FOUND (Aggregated Clusters):\n{obs_text}"))
        # -----------------------------------------------

        steps: list[InvestigationStep] = []
        final_answer_dict = {}
        
        for i in range(self.max_iterations):
            if i > 0:
                await asyncio.sleep(self.min_iteration_delay)
            
            try:
                await self._wait_for_rate_limit()
                raw_response = await self.llm.complete(messages)
                parsed = parse_llm_response(raw_response)
                
                thought = Thought(content=parsed.get("thought", ""))
                action = None
                observation = None
                
                if "action" in parsed:
                    tool_name = parsed["action"].get("tool")
                    tool_args = parsed["action"].get("args", {})
                    action = Action(tool_call=ToolCall(name=tool_name, args=tool_args))
                    
                    if tool_name in self.tools:
                        try:
                            result = await self.tools[tool_name](**tool_args)
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name,
                                args=tool_args,
                                result=result
                            ))
                            
                            # Track Evidence
                            new_chunks = self._extract_chunks(result)
                            for chunk in new_chunks:
                                cid = chunk["chunk_id"]
                                if cid not in self._evidence_chunk_ids:
                                    self._evidence_chunk_ids.add(cid)
                                    self._evidence_chunks.append(chunk)
                                    
                        except Exception as e:
                            logger.error(f"Tool failed: {e}")
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name,
                                args=tool_args,
                                result=None,
                                error=str(e)
                            ))
                    else:
                        observation = Observation(tool_result=ToolResult(
                            tool_name=tool_name,
                            args=tool_args,
                            result=None,
                            error=f"Unknown tool '{tool_name}'"
                        ))
                    
                step = InvestigationStep(i + 1, thought, action, observation)
                steps.append(step)
                if on_step: await on_step(step)
                
                if "answer" in parsed:
                    final_answer_dict = parsed["answer"]
                    break
                
                messages.append(Message(role="assistant", content=raw_response))
                if observation and observation.tool_result:
                    res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                    messages.append(Message(role="user", content=f"Observation:\n{json.dumps(res, default=str, indent=2)}"))
                
            except Exception as e:
                logger.error(f"Step {i+1} failed: {e}")
                messages.append(Message(role="user", content=f"Error in previous step: {str(e)}. Please recover and continue."))

        # Final Ans Enhancement
        if not final_answer_dict:
            final_answer_dict = {"summary": "Max iterations reached without conclusion.", "confidence": "low"}

        # Grounding Enforcement: Inject evidence into final answer if missing or sparse
        if "evidence" not in final_answer_dict or not final_answer_dict["evidence"]:
            final_answer_dict["evidence"] = [
                {
                    "service": c.get("source_service") or c.get("service"), 
                    "timestamp": c.get("timestamp_start") or c.get("timestamp"), 
                    "message": c.get("text")
                }
                for c in self._evidence_chunks[:10]
            ]

        return InvestigationResult(
            query=query,
            steps=steps,
            answer=json.dumps(final_answer_dict, indent=2),
            evidence_chunk_ids=list(self._evidence_chunk_ids),
            confidence=final_answer_dict.get("confidence", "low"),
            duration_seconds=time.time() - start_time,
            evidence=final_answer_dict.get("evidence", [])
        )

    def _build_system_prompt(self) -> str:
        return f"""You are a senior SRE investigating distributed system failures using logs.

KNOWN SERVICES:
{self.known_services}

INVESTIGATION TOOLS:
{json.dumps(TOOL_SCHEMAS, indent=2)}

RULES:
1. NEVER assume missing logs = system failure.
2. ALWAYS expand time window or search broad keywords before concluding absence of data.
3. ALWAYS correlate across services (auth, api-gateway, payment, user, db).
4. ALWAYS identify root cause (e.g., db-service pool exhaustion), not just symptoms (e.g., auth-service 503).
5. ALWAYS reason using timestamps and causal order. Trace BACKWARD from symptoms to root causes.
6. Prefer infrastructure/dependency issues (DB, Network, Redis) over leaf service code bugs unless proven.
7. Stop when a clear causal chain is established and supported by multiple log events.
8. Every claim MUST be backed by logs. Reference at least 2 log events for the root cause.
9. If you encounter sparse logs, try searching for "error", "fail", "timeout", or "exception" across all services.

INVESTIGATION STRATEGY:
Step 1: Identify failing services (via get_service_summary / search_logs)
Step 2: Correlate errors across services (via timestamps, request_ids, or co-occurrence)
Step 3: Trace dependency chain backward to find the source
Step 4: Identify root cause and supporting evidence
Step 5: Validate findings against the timeline

RESPONSE FORMATS:

FORMAT A (Tool Call):
{{
  "thought": "description of your current goal and reasoning",
  "action": {{ "tool": "tool_name", "args": {{ ... }} }}
}}

FORMAT B (Final Answer):
{{
  "thought": "summary of findings and causal reasoning",
  "answer": {{
    "summary": "Full paragraph describing the incident and its progression.",
    "root_cause": "The specific technical root cause (be precise).",
    "evidence": [
      {{ "service": "...", "timestamp": "...", "message": "..." }}
    ],
    "causal_chain": ["Event A -> Event B -> Event C"],
    "impacted_services": ["service-a", "service-b"],
    "confidence": "high | medium | low",
    "confidence_reasoning": "rationale for confidence based on log coverage"
  }}
}}

Current UTC time: {datetime.utcnow().isoformat()}
CRITICAL: Entire response must be a single JSON object. Do not add text outside the JSON.
"""
