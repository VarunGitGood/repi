"""Answer compilation — a focused LLM call that turns gathered evidence into
a validated InvestigationAnswer.

This module is invoked by `ReactInvestigationLoop.investigate` after the
gathering phase exits. Its only job is to produce the final answer from
the evidence the loop collected — it does NOT call tools, does NOT plan,
does NOT investigate. Keeping the compile phase narrow gives the LLM a
single task that fits cleanly in one prompt.

Three layers from most-preferred to last-resort:

1. The compiler LLM call (`compile_answer`) with one validation retry.
2. Server-side enforcement (`enforce_floors` from schema.py) downgrades
   confidence if the model overclaims relative to the evidence.
3. Deterministic synth (`synthesize_answer`) — a non-LLM fallback that
   produces an honest "unable to determine" answer from the tool ledger.
   Triggers only if the compile call fails twice or the provider errors.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from repi.llm.provider import LLMProvider, Message
from repi.llm.json_utils import parse_llm_response
from repi.investigation.schema import validate_answer, enforce_floors

logger = logging.getLogger(__name__)


COMPILER_SYSTEM_PROMPT = """\
You compile an investigation report from gathered evidence. The investigation
has already finished — your job is NOT to investigate further, but to summarize
what was found into one structured answer.

Output ONLY a valid JSON object matching the InvestigationAnswer schema below.
No commentary, no markdown fences, no explanations outside the JSON.

CITATION RULE: you may ONLY reference `chunk_id` values that appear in the
provided evidence list. Inventing or guessing any chunk_id is a protocol
violation.

HONESTY RULE: if the evidence is weak, contradictory, or absent, set
`confidence="low"`, list the specific missing telemetry in `gaps`, and write
`root_cause` honestly (e.g. "unable to determine; signals consistent with X
but no direct evidence of Y"). Do NOT invent a confident root cause when the
evidence does not support one.

COMPLETENESS RULE: `affected_services` MUST include every service that
produced at least one chunk in the evidence list. A service mentioned in
another service's log line (e.g. "caller=api-gateway") is also valid and
should be included if it's part of the incident chain.

RULED-OUT RULE (important — most-skipped step): every KNOWN service that
appeared in the evidence (or was searched but returned nothing) but is NOT
in your `affected_services` list MUST appear in `ruled_out_hypotheses` with
a one-line rationale. Acceptable rationales:
  - "no errors in this window"
  - "only downstream symptom of <other-service>"
  - "coincidental activity, no causal link"
  - "appears in logs but the timing doesn't match the incident window"
Generic hypotheses like "network outage" do NOT count — name the specific
service. Two or three concrete ruled-out entries is the floor, not the ceiling.

CONFIDENCE RULE: if you cite ≥3 chunk_ids in trigger_event + propagation_chain
AND the root_cause is supported by those citations end-to-end, you SHOULD
emit `confidence="high"`. Reserve `"medium"` for partial chains, `"low"` for
genuinely unsupported answers. Listing gaps is encouraged but not required
when confidence is high.

InvestigationAnswer schema:
{
  "incident_window": {"start": "ISO8601", "end": "ISO8601"},
  "affected_services": ["service-a", ...],
  "trigger_event": {
    "chunk_id": "<must be from evidence>",
    "service": "...", "timestamp": "ISO8601", "log_line": "..."
  },
  "propagation_chain": [
    {"service": "...", "chunk_id": "<from evidence>", "ts": "ISO8601", "what": "..."}
  ],
  "root_cause": "one or two sentences explaining the mechanism",
  "ruled_out_hypotheses": [
    {"hypothesis": "...", "why_ruled_out": "..."}
  ],
  "assumptions": ["..."],
  "confidence": "high" | "medium" | "low",
  "gaps": ["..."]
}
"""


@dataclass
class CompileResult:
    answer: dict
    source: str
    attempts: int
    floor_adjustments: list[str] = field(default_factory=list)


def _evidence_summary(evidence: list[dict], limit: int = 60) -> list[dict]:
    out: list[dict] = []
    for c in evidence[:limit]:
        out.append({
            "chunk_id": c.get("chunk_id"),
            "service": c.get("service"),
            "timestamp": str(c.get("timestamp", "")),
            "level": c.get("level", ""),
            "message": (c.get("message") or c.get("text") or "")[:300],
        })
    return out


def _ledger_summary(ledger: dict[str, dict]) -> list[str]:
    lines: list[str] = []
    for entry in ledger.values():
        try:
            args_str = json.dumps(entry.get("args", {}), default=str, sort_keys=True)
        except (TypeError, ValueError):
            args_str = repr(entry.get("args"))
        lines.append(f"{entry.get('tool_name', 'unknown')}({args_str})")
    return lines


def _services_in_evidence(evidence: list[dict]) -> list[str]:
    seen: list[str] = []
    for c in evidence:
        svc = c.get("service")
        if svc and svc not in seen:
            seen.append(svc)
    return seen


def _build_compile_messages(
    query: str,
    resolved_intent: Optional[Any],
    evidence: list[dict],
    tool_ledger: dict[str, dict],
    recent_thoughts: list[str],
    validation_errors: Optional[list[str]] = None,
    known_services: Optional[list[str]] = None,
) -> list[Message]:
    intent_block: dict[str, Any] = {}
    if resolved_intent is not None:
        intent_block = {
            "time_from": str(getattr(resolved_intent, "time_from", "") or ""),
            "time_to": str(getattr(resolved_intent, "time_to", "") or ""),
            "services": list(getattr(resolved_intent, "services", []) or []),
            "assumed": list(getattr(resolved_intent, "assumed", []) or []),
        }

    payload = {
        "query": query,
        "resolved_intent": intent_block,
        "known_services": list(known_services or []),
        "tool_calls_issued": _ledger_summary(tool_ledger),
        "evidence_chunks": _evidence_summary(evidence),
        "recent_thoughts": recent_thoughts[-3:],
    }

    user_lines = [
        "## Evidence package",
        "",
        "```json",
        json.dumps(payload, indent=2, default=str),
        "```",
        "",
        "Compile the InvestigationAnswer now. Output only the JSON object.",
    ]

    if validation_errors:
        user_lines.extend([
            "",
            "## Previous attempt failed validation",
            "Your last reply produced these errors:",
            *[f"- {e}" for e in validation_errors],
            "Fix them and reply again with ONLY the JSON object.",
        ])

    return [
        Message(role="system", content=COMPILER_SYSTEM_PROMPT),
        Message(role="user", content="\n".join(user_lines)),
    ]


def synthesize_answer(
    query: str,
    resolved_intent: Optional[Any],
    evidence: list[dict],
    tool_ledger: dict[str, dict],
    extra_gaps: Optional[list[str]] = None,
) -> dict:
    """Deterministic last-resort answer. Uses only what the tools actually
    returned — no LLM, no invention. Always returns confidence='low'."""
    services = _services_in_evidence(evidence)

    trigger: dict[str, Any] = {}
    for c in evidence:
        lvl = (c.get("level") or "").upper()
        if lvl in {"ERROR", "WARNING", "CRITICAL", "FATAL"}:
            trigger = {
                "chunk_id": c.get("chunk_id", ""),
                "service": c.get("service", ""),
                "timestamp": str(c.get("timestamp", "")),
                "log_line": (c.get("message") or c.get("text") or "")[:500],
            }
            break

    incident_window: dict[str, str] = {}
    if resolved_intent is not None:
        tf = getattr(resolved_intent, "time_from", None)
        tt = getattr(resolved_intent, "time_to", None)
        if tf:
            incident_window["start"] = str(tf)
        if tt:
            incident_window["end"] = str(tt)

    assumptions: list[str] = []
    if resolved_intent is not None:
        assumptions = list(getattr(resolved_intent, "assumed", []) or [])

    gaps = [
        "Compiler LLM call did not return a valid answer; falling back to "
        "deterministic synthesis from the tool-call ledger.",
        f"Tools attempted: {sorted({e.get('tool_name', '?') for e in tool_ledger.values()})}",
    ]
    if extra_gaps:
        gaps.extend(extra_gaps)
    if not evidence:
        gaps.append("No evidence chunks were retrieved during gathering.")

    return {
        "incident_window": incident_window,
        "affected_services": services,
        "trigger_event": trigger,
        "propagation_chain": [],
        "root_cause": (
            "unable_to_determine — loop and compile call did not finalize; "
            "see gaps for details."
        ),
        "ruled_out_hypotheses": [],
        "assumptions": assumptions,
        "confidence": "low",
        "gaps": gaps,
    }


async def compile_answer(
    llm: LLMProvider,
    query: str,
    resolved_intent: Optional[Any],
    evidence: list[dict],
    tool_ledger: dict[str, dict],
    recent_thoughts: Optional[list[str]] = None,
    known_services: Optional[list[str]] = None,
    *,
    max_tokens: int = 4000,
) -> CompileResult:
    """Run the compile LLM call. Validates and retries once on validation
    failure. Falls through to deterministic synth on persistent errors.
    Applies server-side enforce_floors to whatever the LLM produces.

    The shared parser comes from `repi.llm.json_utils`.
    """
    evidence_ids = {c.get("chunk_id") for c in evidence if c.get("chunk_id")}
    recent = recent_thoughts or []
    validation_errors: Optional[list[str]] = None
    last_parsed: dict = {}
    attempts_made = 0

    for attempt in range(1, 3):
        attempts_made = attempt
        messages = _build_compile_messages(
            query=query,
            resolved_intent=resolved_intent,
            evidence=evidence,
            tool_ledger=tool_ledger,
            recent_thoughts=recent,
            validation_errors=validation_errors,
            known_services=known_services,
        )
        try:
            raw = await llm.complete(messages, max_tokens=max_tokens, temperature=0.0)
        except Exception as exc:
            logger.warning("Compiler LLM call attempt %d raised: %s", attempt, exc)
            break

        try:
            parsed = parse_llm_response(raw)
        except Exception as exc:
            logger.warning("Compiler reply attempt %d failed to parse: %s", attempt, exc)
            validation_errors = [f"reply was not valid JSON: {exc}"]
            continue

        last_parsed = parsed
        is_valid, errors = validate_answer(parsed, evidence_ids)
        if is_valid:
            adjusted, adjustments = enforce_floors(
                parsed, evidence,
                resolved_entities=list(getattr(resolved_intent, "entities", []) or []),
            )
            return CompileResult(
                answer=adjusted,
                source="llm",
                attempts=attempt,
                floor_adjustments=adjustments,
            )

        logger.info("Compiler answer failed validation on attempt %d: %s", attempt, errors)
        validation_errors = errors

    if last_parsed:
        adjusted, adjustments = enforce_floors(
            last_parsed, evidence,
            resolved_entities=list(getattr(resolved_intent, "entities", []) or []),
        )
        adjusted.setdefault("gaps", []).append(
            f"Compiler answer failed validation after {attempts_made} attempt(s): {validation_errors}"
        )
        adjusted["confidence"] = "low"
        return CompileResult(
            answer=adjusted,
            source="llm_invalid",
            attempts=attempts_made,
            floor_adjustments=adjustments,
        )

    synthesized = synthesize_answer(
        query=query,
        resolved_intent=resolved_intent,
        evidence=evidence,
        tool_ledger=tool_ledger,
    )
    return CompileResult(
        answer=synthesized,
        source="deterministic",
        attempts=attempts_made,
        floor_adjustments=[],
    )
