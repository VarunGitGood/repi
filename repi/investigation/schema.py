from __future__ import annotations
from pydantic import BaseModel


class TriggerEvent(BaseModel):
    chunk_id: str
    service: str
    timestamp: str
    log_line: str


class PropagationHop(BaseModel):
    service: str
    chunk_id: str
    ts: str
    what: str


class RuledOutHypothesis(BaseModel):
    hypothesis: str
    why_ruled_out: str


class InvestigationAnswer(BaseModel):
    incident_window: dict
    affected_services: list[str]
    trigger_event: TriggerEvent
    propagation_chain: list[PropagationHop]
    root_cause: str
    ruled_out_hypotheses: list[RuledOutHypothesis]
    assumptions: list[str]
    confidence: str
    gaps: list[str]


def validate_answer(answer_dict: dict, evidence_chunk_ids: set[str]) -> tuple[bool, list[str]]:
    errors: list[str] = []

    confidence = answer_dict.get("confidence", "")
    if confidence not in {"high", "medium", "low"}:
        errors.append(f"confidence must be 'high', 'medium', or 'low', got: {confidence!r}")

    trigger = answer_dict.get("trigger_event") or {}
    trigger_cid = trigger.get("chunk_id", "")
    if trigger_cid and evidence_chunk_ids and trigger_cid not in evidence_chunk_ids:
        errors.append(f"trigger_event.chunk_id {trigger_cid!r} is not in the evidence pool")

    chain = answer_dict.get("propagation_chain") or []
    affected = answer_dict.get("affected_services") or []
    if len(affected) >= 2 and len(chain) == 0:
        errors.append("propagation_chain must not be empty when affected_services has 2 or more entries")

    for hop in chain:
        cid = hop.get("chunk_id", "")
        if cid and evidence_chunk_ids and cid not in evidence_chunk_ids:
            errors.append(f"propagation_chain chunk_id {cid!r} is not in the evidence pool")

    ruled_out = answer_dict.get("ruled_out_hypotheses") or []
    if len(ruled_out) == 0 and confidence != "high":
        errors.append("ruled_out_hypotheses must not be empty when confidence is not 'high'")

    return (len(errors) == 0, errors)
