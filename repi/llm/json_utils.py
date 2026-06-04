"""Shared JSON-extraction helpers for LLM replies.

Lifted out of `repi.investigation.react_loop` so the eval judge can use the
same robust parser (Issue #49). Behavior is identical to the prior
`react_loop.parse_llm_response` — markdown fences, common prefixes, JS
comments, and embedded JSON objects are all handled.
"""
from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger(__name__)


def _strip_js_comments(text: str) -> str:
    """Remove /* block comments */ and // line comments from JSON-like text.
    Only strips // when it starts a line (after optional whitespace) so we
    don't corrupt URLs like http:// inside string values."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//[^\n]*", "", text, flags=re.MULTILINE)
    return text


def _extract_json_objects(text: str) -> list[dict]:
    objects: list[dict] = []
    depth = 0
    start: int | None = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start:i + 1]
                try:
                    objects.append(json.loads(candidate))
                except json.JSONDecodeError:
                    pass
                start = None
    return objects


def parse_llm_response(raw: str) -> dict:
    """Extract and parse JSON from an LLM reply.

    Handles:
      - markdown fences (```json ... ``` or plain ``` ... ```)
      - common prefixes like "Tool Call:" / "Final Answer:"
      - JS-style /* block */ and // line comments
      - multiple top-level JSON objects (merged left-to-right)

    Raises ValueError if no JSON can be extracted.
    """
    cleaned = re.sub(r"```json|```", "", raw).strip()
    cleaned = re.sub(r"^(?:Tool Call|Final Answer):\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = _strip_js_comments(cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    objects = _extract_json_objects(cleaned)
    if not objects:
        logger.error(
            "Failed to parse JSON from LLM response. Raw length: %d. Raw content: %s",
            len(raw), raw,
        )
        raise ValueError("No valid JSON found in LLM response. Check logs for full content.")

    if len(objects) == 1:
        return objects[0]

    merged: dict = {}
    for obj in objects:
        merged.update(obj)
    return merged
