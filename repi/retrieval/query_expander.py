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

MAX_VARIANTS = 3
"""Total cap on the variant list (including the original). Each variant
doubles RRF fan-out — one vector + one FTS query per leg, per variant — so
the cap directly bounds /chat latency. The expander fills the budget from
cheap-to-expensive: original first, static-dictionary synonyms next, and
the LLM is only called if there's still room. Static dictionaries are
deterministic and free; an LLM roundtrip is hundreds of ms — calling it
when the budget is already full would only do work that gets truncated."""


class QueryExpander:
    def __init__(self, llm: Optional[LLMProvider] = None) -> None:
        self.llm = llm

    async def expand(self, query: str) -> List[str]:
        # Static expansion first, then dedup case-insensitively. The static
        # expander is bounded internally; the dedup pass tells us how much of
        # the MAX_VARIANTS budget is still unfilled.
        #
        # Dedup key normalises case AND collapses internal whitespace —
        # "kafka broker" and "kafka   broker" tokenize identically to both the
        # FTS and embedding legs, so treating them as separate variants would
        # just double the RRF fan-out for the same retrieval.
        def _key(v: str) -> str:
            return " ".join(v.lower().split())

        variants = expand_query_static(query)
        seen_lower: set[str] = set()
        deduped: List[str] = []
        for v in variants:
            key = _key(v)
            if not key or key in seen_lower:
                continue
            seen_lower.add(key)
            deduped.append(v)

        # Only spend an LLM roundtrip if static variants didn't already fill
        # the cap. Ask for exactly the room that's left so the slice below
        # doesn't truncate work we paid latency for.
        room = MAX_VARIANTS - len(deduped)
        if room > 0 and self.llm is not None:
            try:
                llm_variants = await self._llm_expand(query)
                for v in llm_variants:
                    key = _key(v)
                    if not key or key in seen_lower:
                        continue
                    seen_lower.add(key)
                    deduped.append(v)
                    if len(deduped) >= MAX_VARIANTS:
                        break
            except Exception as e:
                logger.warning(f"LLM query expansion failed: {e}")

        return deduped[:MAX_VARIANTS]

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
