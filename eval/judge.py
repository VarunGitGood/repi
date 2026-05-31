"""LLM-as-judge scorer for repi eval datasets.

Replaces the hand-coded per-dataset graders with a single LLM call that
evaluates the investigation answer against criteria derived from expected.json.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from repi.llm.provider import LLMProvider, Message
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
2. Each criterion gets a score from 0.0 to 1.0:
   - 1.0 = fully correct
   - 0.7-0.9 = mostly correct with minor omissions
   - 0.4-0.6 = partially correct, significant gaps
   - 0.1-0.3 = mostly wrong or missing key elements
   - 0.0 = completely wrong or absent
3. Provide a brief explanation for each score.
4. Return ONLY valid JSON — no markdown fences, no commentary outside the JSON.

Return this exact JSON structure:
{
  "scores": [
    {"name": "<criterion_name>", "score": <float 0.0-1.0>, "explanation": "<why>"},
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


def _parse_judge_response(
    raw: str,
    dataset_name: str,
    model_under_test: str,
    judge_model: str,
    criterion_names: list[str],
) -> JudgeResult:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Judge returned unparseable response: %s", exc)
        criteria = [
            CriterionScore(name=n, score=0.0, explanation="Judge response was not valid JSON.")
            for n in criterion_names
        ]
        return JudgeResult(
            dataset=dataset_name,
            model_under_test=model_under_test,
            judge_model=judge_model,
            aggregate_score=0.0,
            criteria=criteria,
            raw_judge_response=raw,
        )

    scores_raw = parsed.get("scores", [])

    scored: dict[str, CriterionScore] = {}
    for entry in scores_raw:
        name = entry.get("name", "")
        if name not in set(criterion_names):
            continue
        scored[name] = CriterionScore(
            name=name,
            score=max(0.0, min(1.0, float(entry.get("score", 0)))),
            explanation=entry.get("explanation", ""),
        )

    criteria: list[CriterionScore] = []
    for name in criterion_names:
        if name in scored:
            criteria.append(scored[name])
        else:
            criteria.append(CriterionScore(
                name=name,
                score=0.0,
                explanation="Judge did not return a score for this criterion.",
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


class LLMJudge:
    def __init__(self, llm: LLMProvider):
        self._llm = llm

    @property
    def model_name(self) -> str:
        return self._llm.model_name

    async def score(
        self,
        answer: dict,
        expected: dict,
        dataset_name: str,
        model_under_test: str,
    ) -> JudgeResult:
        criterion_names = active_criterion_names(expected)
        criteria_text = build_criteria(expected)
        messages = _build_judge_prompt(answer, expected, criteria_text, criterion_names)

        raw = await self._llm.complete(messages, max_tokens=2000, temperature=0.0)

        return _parse_judge_response(
            raw=raw,
            dataset_name=dataset_name,
            model_under_test=model_under_test,
            judge_model=self._llm.model_name,
            criterion_names=criterion_names,
        )
