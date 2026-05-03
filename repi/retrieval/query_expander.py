from __future__ import annotations
import json
import logging
from typing import List, Dict, Any, Optional
from repi.llm.provider import LLMProvider, Message

logger = logging.getLogger(__name__)

LOG_SYNONYMS: Dict[str, List[str]] = {
    "error": ["exception", "failed", "failure", "fatal", "traceback", "panic", "crash"],
    "timeout": ["timed out", "deadline exceeded", "connection timeout", "read timeout"],
    "connection": ["connect", "socket", "network", "refused", "unreachable"],
    "auth": ["authentication", "authorization", "token", "credential", "unauthorized", "403", "401"],
    "database": ["db", "postgres", "mysql", "query", "connection pool", "deadlock"],
    "memory": ["oom", "out of memory", "heap", "gc", "garbage collection"],
    "slow": ["latency", "performance", "degraded", "bottleneck", "high response time"],
    "deploy": ["deployment", "rollout", "release", "restart", "pod", "container"],
}

def expand_query_static(query: str) -> List[str]:
    """
    Generate query variants based on a static synonym dictionary.
    """
    variants = [query]
    tokens = query.lower().split()
    
    for token in tokens:
        if token in LOG_SYNONYMS:
            for synonym in LOG_SYNONYMS[token]:
                # Simple replacement for now
                new_variant = query.lower().replace(token, synonym)
                if new_variant not in variants:
                    variants.append(new_variant)
                if len(variants) >= 4:
                    break
        if len(variants) >= 4:
            break
            
    return variants[:4]

class QueryExpander:
    def __init__(self, llm: Optional[LLMProvider] = None) -> None:
        self.llm = llm

    async def expand(self, query: str) -> List[str]:
        # Always run static expansion
        variants = expand_query_static(query)
        
        # If LLM configured, add up to 2 more LLM-generated variants
        if self.llm is not None:
            try:
                llm_variants = await self._llm_expand(query)
                variants.extend(llm_variants[:2])
            except Exception as e:
                logger.warning(f"LLM query expansion failed: {e}")
        
        # Deduplicate, preserve order
        seen = set()
        return [v for v in variants if not (v in seen or seen.add(v))]

    async def _llm_expand(self, query: str) -> List[str]:
        prompt = f"""Generate 2 alternative phrasings of this log search query using different 
technical terminology that might appear in actual log files.
Return ONLY a JSON array. Example: ["conn refused", "socket timeout"]
Query: {query}"""
        
        response = await self.llm.complete(
            messages=[Message(role="user", content=prompt)],
            max_tokens=200
        )
        
        # Strip markdown fences
        content = response.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:].strip()
        
        try:
            expanded = json.loads(content)
            if isinstance(expanded, list):
                return [str(v) for v in expanded]
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM expansion response: {content}")
            
        return []
