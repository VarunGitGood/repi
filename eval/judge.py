"""LLM-as-judge scorer for repi eval datasets.

Replaces the hand-coded per-dataset graders with a single LLM call that
evaluates the investigation answer against criteria derived from expected.json.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from repi.llm.provider import LLMProvider, Message
from repi.llm.json_utils import parse_llm_response
from eval.criteria import build_criteria, active_criterion_names
from eval.results import CriterionScore, JudgeResult

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 0.8

JUDGE_SYSTEM_PROMPT = """\
You are an evaluation judge for a log-investigation engine called repi.

repi ingests log files and uses an LLM-driven ReAct loop to investigate
incidents. It produces structured JSON answers with these fields:
- trigger_event: the originating service + log line
- root_cause: natural-language explanation of what went wrong
- affected_services: list of impacted services
- propagation_chain: ordered list of causal hops (service → service)
- ruled_out_hypotheses: services/theories considered and dismissed
- confidence: "high", "medium", or "low"
- gaps: evidence that was missing or unavailable
- assumptions: interpretations the system made about ambiguous input
- incident_window: time range of the incident

Your job is to score an investigation answer against a set of criteria.

IMPORTANT RULES:
1. Score SEMANTIC correctness, not exact string matches. "pool exhausted" and
   "exhausting its connection pool" mean the same thing. "key rotation" and
   "rotated the signing key" are equivalent.
2. For each criterion, FIRST write the explanation describing what the answer
   got right and what it missed, THEN choose a score that is consistent with
   that explanation. Do not commit to a number before you have reasoned about
   the evidence — score-first reasoning produces post-hoc rationalisations.
3. Each criterion gets a score from 0.0 to 1.0:
   - 1.0 = fully correct
   - 0.7-0.9 = mostly correct with minor omissions
   - 0.4-0.6 = partially correct, significant gaps
   - 0.1-0.3 = mostly wrong or missing key elements
   - 0.0 = completely wrong or absent
4. Return ONLY valid JSON — no markdown fences, no commentary outside the JSON.

Return this exact JSON structure (note: explanation comes BEFORE score):
{
  "scores": [
    {"name": "<criterion_name>", "explanation": "<reasoning>", "score": <float 0.0-1.0>},
    ...
  ]
}
"""


def _build_judge_prompt(
    answer: dict,
    expected: dict,
    criteria_text: str,
    criterion_names: list[str],
) -> list[Message]:
    user_content = (
        f"## Criteria to evaluate\n\n"
        f"{criteria_text}\n\n"
        f"## Criterion names to score\n\n"
        f"You MUST return a score for each of these criteria: {json.dumps(criterion_names)}\n\n"
        f"## Investigation answer to evaluate\n\n"
        f"```json\n{json.dumps(answer, indent=2)}\n```"
    )
    return [
        Message(role="system", content=JUDGE_SYSTEM_PROMPT),
        Message(role="user", content=user_content),
    ]


def _parse_judge_payload(raw: str) -> dict | None:
    """Try to extract the judge's scores JSON from a raw reply. Returns None
    if no JSON can be parsed at all. Uses the shared `parse_llm_response`
    helper for robust fence/comment/embedded-object handling."""
    try:
        return parse_llm_response(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("Judge reply could not be parsed: %s", exc)
        return None


def _scores_from_parsed(
    parsed: dict,
    criterion_names: list[str],
) -> dict[str, CriterionScore]:
    out: dict[str, CriterionScore] = {}
    for entry in parsed.get("scores", []) or []:
        name = entry.get("name", "")
        if name not in set(criterion_names):
            continue
        out[name] = CriterionScore(
            name=name,
            score=max(0.0, min(1.0, float(entry.get("score", 0)))),
            explanation=entry.get("explanation", ""),
        )
    return out


def _judge_result_from_scores(
    *,
    dataset_name: str,
    model_under_test: str,
    judge_model: str,
    criterion_names: list[str],
    scored: dict[str, CriterionScore],
    raw: str,
    not_scored_explanation: str = "Judge did not return a score for this criterion.",
) -> JudgeResult:
    criteria: list[CriterionScore] = []
    for name in criterion_names:
        criteria.append(scored.get(name) or CriterionScore(
            name=name, score=0.0, explanation=not_scored_explanation,
        ))
    aggregate = sum(c.score for c in criteria) / len(criteria) if criteria else 0.0
    return JudgeResult(
        dataset=dataset_name,
        model_under_test=model_under_test,
        judge_model=judge_model,
        aggregate_score=round(aggregate, 3),
        criteria=criteria,
        raw_judge_response=raw,
    )


def deterministic_precheck(answer: dict) -> Optional[list[str]]:
    """Fast sanity checks before spending LLM tokens on judging.
    Returns a list of fatal errors, or None if the answer is worth judging."""
    errors: list[str] = []

    if not answer:
        errors.append("Answer is empty or not valid JSON.")
        return errors

    required = ["confidence", "root_cause", "affected_services"]
    for field in required:
        if field not in answer or not answer[field]:
            errors.append(f"Missing required field: {field}")

    confidence = answer.get("confidence", "")
    if confidence and confidence not in {"high", "medium", "low"}:
        errors.append(f"Invalid confidence value: {confidence!r}")

    return errors if errors else None


DETERMINISTIC_CRITERIA = {"confidence_calibration", "gap_awareness"}


def score_deterministic(answer: dict, expected: dict) -> dict[str, CriterionScore]:
    """Score criteria that can be evaluated without an LLM call."""
    ea = expected.get("expected_answer", {})
    scores: dict[str, CriterionScore] = {}

    # confidence_calibration: exact string match
    expected_conf = ea.get("confidence")
    if expected_conf:
        actual_conf = answer.get("confidence", "")
        if actual_conf == expected_conf:
            scores["confidence_calibration"] = CriterionScore(
                name="confidence_calibration",
                score=1.0,
                explanation=f"Confidence correctly set to '{expected_conf}'.",
            )
        else:
            scores["confidence_calibration"] = CriterionScore(
                name="confidence_calibration",
                score=0.0,
                explanation=f"Expected confidence '{expected_conf}', got '{actual_conf}'.",
            )

    # gap_awareness: keyword overlap check
    gaps_required = ea.get("gaps_must_include_one_of")
    if gaps_required:
        gaps = answer.get("gaps") or []
        if not gaps:
            scores["gap_awareness"] = CriterionScore(
                name="gap_awareness",
                score=0.0,
                explanation="Gaps list is empty.",
            )
        else:
            gaps_text = " ".join(str(g).lower() for g in gaps)
            matched = any(
                _keyword_overlap(expected_gap, gaps_text)
                for expected_gap in gaps_required
            )
            if matched:
                scores["gap_awareness"] = CriterionScore(
                    name="gap_awareness",
                    score=1.0,
                    explanation="Gaps list includes content matching expected gaps.",
                )
            else:
                scores["gap_awareness"] = CriterionScore(
                    name="gap_awareness",
                    score=0.4,
                    explanation="Gaps list is non-empty but doesn't clearly match expected gap descriptions.",
                )

    return scores


def _keyword_overlap(expected_phrase: str, actual_text: str) -> bool:
    """Check whether enough content words from the expected phrase appear in the
    actual text. Skips short filler words (≤3 chars) to focus on meaningful terms."""
    keywords = [w for w in expected_phrase.lower().split() if len(w) > 3]
    if not keywords:
        return expected_phrase.lower() in actual_text
    hits = sum(1 for k in keywords if k in actual_text)
    return hits / len(keywords) >= 0.4


_PARSE_RETRY_USER_PROMPT = (
    "Your previous reply could not be parsed as JSON. Reply again with ONLY "
    "the JSON object matching the {\"scores\": [...]} shape — no commentary, "
    "no markdown fences."
)


class LLMJudge:
    def __init__(self, llm: LLMProvider):
        self._llm = llm
        # Populated per `score()` call so callers can introspect after a run.
        self.last_parse_attempts: int = 0

    @property
    def model_name(self) -> str:
        return self._llm.model_name

    async def _ask_judge(
        self,
        messages: list[Message],
    ) -> tuple[str, dict | None, int]:
        """Issue the judge LLM call. On parse failure, retry once with a
        clarification turn. Returns (last_raw_reply, parsed_or_None, attempts)."""
        raw = await self._llm.complete(messages, max_tokens=2000, temperature=0.0)
        parsed = _parse_judge_payload(raw)
        if parsed is not None:
            return raw, parsed, 1

        retry_messages = messages + [
            Message(role="assistant", content=raw),
            Message(role="user", content=_PARSE_RETRY_USER_PROMPT),
        ]
        raw_retry = await self._llm.complete(retry_messages, max_tokens=2000, temperature=0.0)
        parsed_retry = _parse_judge_payload(raw_retry)
        return raw_retry, parsed_retry, 2

    async def score(
        self,
        answer: dict,
        expected: dict,
        dataset_name: str,
        model_under_test: str,
    ) -> JudgeResult:
        all_names = active_criterion_names(expected)

        det_scores = score_deterministic(answer, expected)
        llm_names = [n for n in all_names if n not in det_scores]

        raw = ""
        llm_scored: dict[str, CriterionScore] = {}
        self.last_parse_attempts = 0

        if llm_names:
            criteria_text = build_criteria(expected, only_names=llm_names)
            messages = _build_judge_prompt(answer, expected, criteria_text, llm_names)
            raw, parsed, attempts = await self._ask_judge(messages)
            self.last_parse_attempts = attempts
            if parsed is not None:
                llm_scored = _scores_from_parsed(parsed, llm_names)

        criteria: list[CriterionScore] = []
        for name in all_names:
            if name in det_scores:
                criteria.append(det_scores[name])
            elif name in llm_scored:
                criteria.append(llm_scored[name])
            else:
                # The judge call ran but returned no score for this name (parse
                # failed, model skipped it, etc). 0.0 with an honest reason.
                explanation = (
                    "Judge response was not valid JSON after retry."
                    if self.last_parse_attempts >= 2 and not llm_scored
                    else "Judge did not return a score for this criterion."
                )
                criteria.append(CriterionScore(name=name, score=0.0, explanation=explanation))

        aggregate = sum(c.score for c in criteria) / len(criteria) if criteria else 0.0

        return JudgeResult(
            dataset=dataset_name,
            model_under_test=model_under_test,
            judge_model=self._llm.model_name,
            aggregate_score=round(aggregate, 3),
            criteria=criteria,
            raw_judge_response=raw,
        )
