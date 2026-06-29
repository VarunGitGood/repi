from __future__ import annotations

import re

MAX_QUERY_LENGTH = 2000

_INJECTION_PATTERNS = [
    re.compile(r"\n\s*(System|Human|Assistant)\s*:", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)\b", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|above|previous)", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|your)\s+(instructions|rules|guidelines)", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(system|prompt|instruction)\s*>", re.IGNORECASE),
]


def sanitize_query(raw: str) -> str:
    if not raw:
        return raw
    cleaned = raw[:MAX_QUERY_LENGTH]
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[filtered]", cleaned)
    return cleaned.strip()
