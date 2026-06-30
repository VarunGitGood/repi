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


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_RANK_TO_CONFIDENCE = {0: "low", 1: "medium", 2: "high"}


def _downgrade_confidence(current: str, by: int = 1) -> str:
    rank = _CONFIDENCE_RANK.get(current, 0)
    return _RANK_TO_CONFIDENCE[max(0, rank - by)]


def _cited_chunk_ids(answer_dict: dict) -> set[str]:
    cited: set[str] = set()
    trig = (answer_dict.get("trigger_event") or {}).get("chunk_id")
    if trig:
        cited.add(trig)
    for hop in answer_dict.get("propagation_chain") or []:
        cid = hop.get("chunk_id")
        if cid:
            cited.add(cid)
    return cited


def enforce_floors(
    answer_dict: dict,
    evidence: list[dict],
    resolved_entities: list[str] | None = None,
) -> tuple[dict, list[str]]:
    """Apply confidence floors and consistency checks server-side.

    Returns (adjusted_answer, list_of_adjustment_notes). The adjusted answer
    is the SAME dict (mutated in-place) — callers that want immutability
    should deep-copy before calling.

    Rules:
      - confidence='high' with <2 distinct cited chunk_ids → downgrade to 'medium'
      - confidence != 'low' with empty gaps → downgrade to 'low'
      - affected_services contains a service never seen in evidence → downgrade one notch
      - 0 evidence chunks → force 'low'
      - any resolved entity present in the query but absent from every chunk's
        text → force 'low' (the entity was the user's anchor and we never
        literally surfaced it).
    """
    notes: list[str] = []

    confidence = (answer_dict.get("confidence") or "").lower()
    if confidence not in _CONFIDENCE_RANK:
        answer_dict["confidence"] = "low"
        notes.append(f"confidence was {confidence!r}; coerced to 'low'")
        confidence = "low"

    # Soft-fail floors — run BEFORE the citation-count rules so the
    # empty-evidence path doesn't slip past "high needs ≥2 citations"
    # (which is silent when there are no citations to count).
    if not evidence:
        if confidence != "low":
            answer_dict["confidence"] = "low"
            gap_msg = "forced low: no evidence chunks were retrieved"
            answer_dict.setdefault("gaps", []).append(gap_msg)
            notes.append(gap_msg)
            confidence = "low"

    if resolved_entities and evidence:
        joined = " ".join(
            str(c.get("message") or c.get("text") or "") for c in evidence
        ).lower()
        missing = [e for e in resolved_entities if e.lower() not in joined]
        if missing and len(missing) == len(resolved_entities):
            # None of the user's anchor IDs literally appear in the gathered text.
            if confidence != "low":
                answer_dict["confidence"] = "low"
                gap_msg = (
                    f"forced low: resolved entities {missing!r} were the query anchor "
                    "but no evidence chunk literally contains any of them"
                )
                answer_dict.setdefault("gaps", []).append(gap_msg)
                notes.append(gap_msg)
                confidence = "low"

    cited = _cited_chunk_ids(answer_dict)
    if confidence == "high" and len(cited) < 2:
        answer_dict["confidence"] = _downgrade_confidence(confidence, by=1)
        confidence = answer_dict["confidence"]
        gap_msg = f"downgraded high→medium: only {len(cited)} chunk_id citation(s) in answer"
        answer_dict.setdefault("gaps", []).append(gap_msg)
        notes.append(gap_msg)

    # "Non-low + no gaps" is no longer an auto-low: a model that produces a
    # rich propagation_chain backed by 3+ chunk citations has actually shown
    # its work, so missing `gaps` is a mild documentation issue, not a sign
    # the answer is unsupported. Downgrade ONE notch (high→medium, medium→low)
    # only when citations are sparse (<3); above that, leave confidence alone
    # but record the missing-gaps fact as a soft signal.
    gaps = answer_dict.get("gaps") or []
    if confidence != "low" and not gaps:
        if len(cited) >= 3:
            note = "no gaps listed despite non-low confidence (≥3 chunk citations — leaving as-is)"
            notes.append(note)
        else:
            answer_dict["confidence"] = _downgrade_confidence(confidence, by=1)
            confidence = answer_dict["confidence"]
            gap_msg = "downgraded one notch: claimed non-low confidence, listed no gaps, <3 citations"
            answer_dict.setdefault("gaps", []).append(gap_msg)
            notes.append(gap_msg)

    # affected_services consistency: only flag services that appear NOWHERE
    # in the evidence — neither as the chunk's `service` field nor anywhere
    # in the chunk text. A service mentioned in another service's log line
    # (e.g. "caller=api-gateway" inside a verification-svc chunk) is real
    # evidence and shouldn't trigger a downgrade.
    evidence_services = {c.get("service") for c in evidence if c.get("service")}
    evidence_text = " ".join(
        str(c.get("message") or c.get("text") or "") for c in evidence
    ).lower()
    affected = answer_dict.get("affected_services") or []
    unseen = [
        s for s in affected
        if s not in evidence_services and s.lower() not in evidence_text
    ]
    if unseen and evidence_services:
        downgraded = _downgrade_confidence(confidence, by=1)
        if downgraded != confidence:
            answer_dict["confidence"] = downgraded
            confidence = downgraded
        gap_msg = (
            f"affected_services {unseen!r} never appeared in tool results or "
            "any chunk text (downgraded confidence one notch as a precaution)"
        )
        answer_dict.setdefault("gaps", []).append(gap_msg)
        notes.append(gap_msg)

    root_cause = str(answer_dict.get("root_cause", "")).lower()
    _HEDGING = ("possibly", "likely", "may have", "might have", "unclear",
                "unable to determine", "hypothesis", "not confirmed",
                "insufficient evidence", "cannot confirm", "uncertain")
    if confidence == "high" and any(h in root_cause for h in _HEDGING):
        answer_dict["confidence"] = "medium"
        confidence = "medium"
        gap_msg = "downgraded high→medium: root_cause contains hedging language"
        answer_dict.setdefault("gaps", []).append(gap_msg)
        notes.append(gap_msg)

    return answer_dict, notes


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
