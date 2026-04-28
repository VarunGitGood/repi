from __future__ import annotations
import json
import logging
import asyncio
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, asdict, field

from src.app.llm.provider import LLMProvider, Message
from src.app.investigation.tools import ToolCall, ToolResult, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

import re

def parse_llm_response(raw: str) -> dict:
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

    # Step 4: merge multiple objects — last one wins per key, but merge carefully
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

class ReactInvestigationLoop:
    def __init__(
        self,
        llm: LLMProvider,
        tools: dict[str, Callable],
        known_services: list[str],
        max_iterations: int = 8,
        min_iteration_delay: float = 2.0,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.known_services = known_services
        self.max_iterations = max_iterations
        self.min_iteration_delay = min_iteration_delay
        self._tool_failure_counts: dict[str, int] = {}
        self._evidence_chunk_ids: set[str] = set()

    def _extract_chunk_ids(self, tool_result: Any) -> list[str]:
        """Extract chunk_id values from any tool result shape (Fix 3)."""
        ids = []
        if isinstance(tool_result, list):
            for item in tool_result:
                if isinstance(item, dict) and "chunk_id" in item:
                    ids.append(item["chunk_id"])
        elif isinstance(tool_result, dict):
            if "chunk_id" in tool_result:
                ids.append(tool_result["chunk_id"])
        return ids

    async def investigate(
        self,
        query: str,
        on_step: Optional[Callable[[InvestigationStep], Awaitable[None]]] = None,
    ) -> InvestigationResult:
        start_time = time.time()
        self._tool_failure_counts = {}  # Reset for each call (Fix 2)
        self._evidence_chunk_ids = set()
        
        messages = [
            Message(role="system", content=self._build_system_prompt()),
            Message(role="user", content=query)
        ]
        
        steps: list[InvestigationStep] = []
        evidence_chunk_ids = set()
        final_answer = ""
        confidence = "medium"
        
        for i in range(self.max_iterations):
            if i > 0:
                await asyncio.sleep(self.min_iteration_delay)
            try:
                raw_response = await self.llm.complete(messages)
                parsed = parse_llm_response(raw_response)
                
                thought = Thought(content=parsed.get("thought", ""))
                action = None
                observation = None
                
                if "action" in parsed:
                    tool_name = parsed["action"].get("tool")
                    tool_args = parsed["action"].get("args", {})
                    action = Action(tool_call=ToolCall(name=tool_name, args=tool_args))
                    
                    # Execute tool
                    if tool_name in self.tools:
                        try:
                            # Tool call - inject required contextual objects (we'll handle this in factory/wiring)
                            result = await self.tools[tool_name](**tool_args)
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name,
                                args=tool_args,
                                result=result
                            ))
                            
                            # Track evidence (Fix 3)
                            extracted_ids = self._extract_chunk_ids(result)
                            for cid in extracted_ids:
                                self._evidence_chunk_ids.add(cid)
                                    
                        except Exception as e:
                            logger.error(f"Tool execution failed: {e}")
                            observation = Observation(tool_result=ToolResult(
                                tool_name=tool_name,
                                args=tool_args,
                                result=None,
                                error=str(e)
                            ))
                            
                            # Circuit breaker (Fix 2)
                            self._tool_failure_counts[tool_name] = self._tool_failure_counts.get(tool_name, 0) + 1
                            if self._tool_failure_counts[tool_name] >= 2:
                                circuit_msg = (
                                    f"SYSTEM: Tool '{tool_name}' has failed {self._tool_failure_counts[tool_name]} times "
                                    f"with the same error. Do not call this tool again in this investigation. "
                                    f"Work with the information you already have or use a different tool."
                                )
                                messages.append(Message(role="user", content=circuit_msg))
                                logger.warning("Circuit breaker triggered for tool '%s'", tool_name)
                    else:
                        observation = Observation(tool_result=ToolResult(
                            tool_name=tool_name,
                            args=tool_args,
                            result=None,
                            error=f"Unknown tool '{tool_name}'. Available: {list(self.tools.keys())}"
                        ))
                    
                step = InvestigationStep(
                    step_number=i + 1,
                    thought=thought,
                    action=action,
                    observation=observation
                )
                steps.append(step)
                
                if on_step:
                    await on_step(step)
                
                if "answer" in parsed:
                    final_answer = json.dumps(parsed["answer"], indent=2)
                    confidence = parsed["answer"].get("confidence", "medium")
                    break
                
                # Prepare for next iteration
                messages.append(Message(role="assistant", content=raw_response))
                
                # Bug 1 Fix: Serialize observation to JSON
                if observation and observation.tool_result:
                    res = observation.tool_result.result if observation.tool_result.result is not None else {"error": observation.tool_result.error}
                    observation_text = json.dumps(res, default=str, indent=2)
                    messages.append(Message(role="user", content=f"Observation:\n{observation_text}"))
                
            except Exception as e:
                logger.error(f"Iteration {i+1} failed: {e}")
                # Inject error back into the loop
                messages.append(Message(role="user", content=f"Error in previous step: {str(e)}. Please try again or provide a final answer if stuck."))

        else:
            # Hit max iterations
            messages.append(Message(role="user", content="Max iterations reached. Produce your best answer now using FORMAT B."))
            try:
                raw_response = await self.llm.complete(messages)
                parsed = parse_llm_response(raw_response)
                final_answer = json.dumps(parsed.get("answer", {}), indent=2)
                confidence = parsed.get("answer", {}).get("confidence", "low")
            except Exception as e:
                final_answer = f"Failed to get final answer after max iterations: {str(e)}"
                confidence = "low"

        return InvestigationResult(
            query=query,
            steps=steps,
            answer=final_answer,
            evidence_chunk_ids=list(self._evidence_chunk_ids),
            confidence=confidence,
            duration_seconds=time.time() - start_time
        )

    def _build_system_prompt(self) -> str:
        return f"""You are an expert SRE investigating a system incident using log data.
Current UTC time: {datetime.utcnow().isoformat()}
Known services: {self.known_services}

You have access to these tools:
{json.dumps(TOOL_SCHEMAS, indent=2)}

At each step you MUST respond with valid JSON in exactly one of these two formats:

FORMAT A — to call a tool:
{{
  "thought": "your reasoning about what to investigate next and why",
  "action": {{
    "tool": "tool_name",
    "args": {{ ... }}
  }}
}}

FORMAT B — when you have enough evidence to answer:
{{
  "thought": "your final reasoning summarizing what you found",
  "answer": {{
    "summary": "one paragraph describing what happened",
    "root_cause": "the specific root cause identified",
    "causal_chain": ["event 1 → event 2 → event 3"],
    "impacted_services": ["service-a", "service-b"],
    "confidence": "high | medium | low",
    "confidence_reasoning": "why you chose this confidence level"
  }}
}}

Rules:
- Always start by getting a service summary before searching chunks
- Use find_co_occurring when you suspect cross-service causation
- Use get_timeline to establish event ordering before drawing causal conclusions
- Only produce FORMAT B when you have evidence from at least 2 tool calls
- Never invent log content — only reference what tools returned
- If tools return empty results, say so explicitly in your answer

"""
