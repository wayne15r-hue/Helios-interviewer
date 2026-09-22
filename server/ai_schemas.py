"""Validated, provider-independent output contracts for Helios.

The browser renders these values as text. No generated code is ever executed.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=16000)]
ShortText = Annotated[str, Field(min_length=1, max_length=2000)]
DimensionKey = Literal["role_knowledge", "relevance", "depth", "structure", "communication"]
DIMENSION_LABELS = {
    "role_knowledge": "Role knowledge",
    "relevance": "Relevance",
    "depth": "Depth",
    "structure": "Answer structure",
    "communication": "Communication",
}


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Requirements(Output):
    requirements: list[ShortText] = Field(min_length=1, max_length=40)


class Gap(Output):
    skill: ShortText
    current_evidence: Text
    gap: Text
    priority: Literal["high", "medium", "low"]


class Topic(Output):
    title: ShortText
    explanation: Text
    exercise: Text


class Level(Output):
    level: Literal["basics", "intermediate", "advanced"]
    title: ShortText
    objectives: list[ShortText] = Field(min_length=1, max_length=12)
    topics: list[Topic] = Field(min_length=1, max_length=12)
    questions: list[ShortText] = Field(min_length=1, max_length=12)


class PracticeRound(Output):
    kind: ShortText
    focus: Text
    practice_questions: list[ShortText] = Field(min_length=1, max_length=12)


class PreparationPlan(Output):
    summary: Text
    skills: list[ShortText] = Field(min_length=1, max_length=40)
    gap_analysis: list[Gap] = Field(min_length=1, max_length=40)
    levels: list[Level] = Field(min_length=3, max_length=3)
    rounds: list[PracticeRound] = Field(min_length=1, max_length=8)
    next_steps: list[ShortText] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def all_levels(self):
        if [level.level for level in self.levels] != ["basics", "intermediate", "advanced"]:
            raise ValueError("Include basics, intermediate, advanced exactly once, in that order")
        return self


class InterviewTurn(Output):
    question: Text
    topic: ShortText
    difficulty: Literal["basics", "intermediate", "advanced"]


class Hint(Output):
    text: Text


class Evidence(Output):
    segment_id: ShortText
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    quote: Text

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Evidence end must follow start")
        return self


class Dimension(Output):
    key: DimensionKey
    label: ShortText
    score: Annotated[int, Field(ge=1, le=5, strict=True)] | None
    feedback: Text
    evidence: list[Evidence] = Field(max_length=12)


class Improvement(Output):
    title: ShortText
    why: Text
    action: Text
    example_answer: Text | None = None


class Drill(Output):
    title: ShortText
    instruction: Text
    skill: ShortText


class AssessmentReport(Output):
    summary: Text
    # Ignored and recomputed by the server from verified, scored dimensions.
    overall_score: float | None = Field(default=None, ge=1, le=5, allow_inf_nan=False)
    dimensions: list[Dimension] = Field(min_length=5, max_length=5)
    strengths: list[ShortText] = Field(max_length=12)
    improvements: list[Improvement] = Field(min_length=3, max_length=3)
    drills: list[Drill] = Field(min_length=1, max_length=8)
    limitations: list[ShortText] = Field(max_length=20)

    @model_validator(mode="after")
    def all_dimensions(self):
        if {dimension.key for dimension in self.dimensions} != set(DIMENSION_LABELS):
            raise ValueError("Include each of the five rubric dimensions exactly once")
        return self
