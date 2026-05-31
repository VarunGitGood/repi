from __future__ import annotations
from pydantic import BaseModel, Field


class CriterionScore(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=1.0)
    explanation: str


class JudgeResult(BaseModel):
    dataset: str
    model_under_test: str
    judge_model: str
    aggregate_score: float = Field(ge=0.0, le=1.0)
    criteria: list[CriterionScore]
    raw_judge_response: str
