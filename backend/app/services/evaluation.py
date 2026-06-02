"""LLM-as-judge evaluation primitives (BD-12 follow-up).

A judge is structurally identical to spec shaping: a StructuredLLM call over a
(rubric, subject) pair that returns a typed result. The only variable part is the
rubric — the dimensions to score on and the passing threshold. Everything else is fixed.

Three levels:
  Level 1 — primitives: EvaluationDimension, EvaluationRubric, DimensionScore, JudgeResult
  Level 2 — evaluate() + get_judge_llm()
  Level 3 — named rubrics: DRIFT_EVIDENCE_RUBRIC (and future additions here)

Usage:
    result = await evaluate(DRIFT_EVIDENCE_RUBRIC, {"memory_summary": ..., "evidence": ...})
    if not result.passed:
        # surface result.warning to the caller; still proceed — human is the arbiter

Judge failures are non-fatal: evaluate() catches LLMError and returns a neutral passing
result so the calling flow is never blocked by a judge outage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.config import JUDGE_MODEL, LLM_API_KEY, LLM_BASE_URL
from app.providers.llm import LLMError, OpenAICompatibleLLM, StructuredLLM


# ---------------------------------------------------------------------------
# Level 1: primitives
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvaluationDimension:
    name: str
    description: str  # what a 5/5 looks like on this axis


@dataclass(frozen=True)
class EvaluationRubric:
    name: str
    dimensions: tuple[EvaluationDimension, ...]
    passing_threshold: float   # 0–1; overall must meet or exceed this to pass
    subject_description: str   # how to describe the thing being judged to the model


class DimensionScore(BaseModel):
    name: str
    score: int        # 1–5
    reasoning: str


class JudgeResult(BaseModel):
    """The structured output of a judge call. Stored as JSONB on the judged object
    so per-dimension scores remain queryable and the schema can evolve without migration."""

    scores: list[DimensionScore]
    overall: float             # mean of (score / 5) across all dimensions; 0–1
    feedback: str              # one-paragraph summary of strengths and weaknesses
    passed: bool               # overall >= rubric.passing_threshold
    warning: str | None = None # specific improvement suggestion when not passed


# ---------------------------------------------------------------------------
# Level 2: evaluate() + get_judge_llm()
# ---------------------------------------------------------------------------

_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":      {"type": "string"},
                    "score":     {"type": "integer", "minimum": 1, "maximum": 5},
                    "reasoning": {"type": "string"},
                },
                "required": ["name", "score", "reasoning"],
            },
        },
        "feedback": {
            "type": "string",
            "description": "One-paragraph summary of what is strong and what is weak.",
        },
        "warning": {
            "type": "string",
            "description": (
                "Specific, actionable improvement suggestion — only present when the "
                "evaluation does not pass the threshold. Omit entirely if it passes."
            ),
        },
    },
    "required": ["scores", "feedback"],
}


def _system_prompt(rubric: EvaluationRubric) -> str:
    dims = "\n".join(
        f"- **{d.name}** (1–5): {d.description}" for d in rubric.dimensions
    )
    return (
        f"You are evaluating {rubric.subject_description}.\n\n"
        f"Score it on the following dimensions:\n{dims}\n\n"
        "1 = very poor, 5 = excellent. Return a score for every dimension listed above, "
        "in order. Be concise and honest — a lenient judge produces useless signal."
    )


def _user_prompt(subject: dict[str, Any]) -> str:
    return "\n\n".join(
        f"{k.replace('_', ' ').capitalize()}:\n{v}"
        for k, v in subject.items()
    )


async def evaluate(
    rubric: EvaluationRubric,
    subject: dict[str, Any],
    *,
    llm: StructuredLLM | None = None,
) -> JudgeResult:
    """Run a judge call over subject using rubric. Returns a JudgeResult with
    per-dimension scores, normalised overall, and a pass/fail verdict.

    Judge failures are non-fatal: LLMError is caught and a neutral passing result is
    returned so the calling flow is never blocked by a judge outage."""
    llm = llm or get_judge_llm()
    try:
        raw = await llm.complete_structured(
            system=_system_prompt(rubric),
            user=_user_prompt(subject),
            schema=_JUDGE_SCHEMA,
            schema_name="evaluation",
        )
    except LLMError:
        return JudgeResult(
            scores=[],
            overall=1.0,
            feedback="Judge unavailable — evaluation skipped.",
            passed=True,
            warning=None,
        )
    scores = [
        DimensionScore(name=s["name"], score=int(s["score"]), reasoning=s["reasoning"])
        for s in raw.get("scores", [])
    ]
    overall = sum(s.score / 5 for s in scores) / len(scores) if scores else 1.0
    passed = overall >= rubric.passing_threshold
    return JudgeResult(
        scores=scores,
        overall=round(overall, 3),
        feedback=raw.get("feedback", ""),
        passed=passed,
        warning=raw.get("warning") if not passed else None,
    )


def get_judge_llm() -> StructuredLLM:
    """Fast, cheap model for inline judgment. Separate from get_shaping_llm() so
    cost-sensitive self-hosters can route judges to a smaller model tier."""
    return OpenAICompatibleLLM(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=JUDGE_MODEL,
        timeout=30.0,  # judges are simpler than shaping — tight timeout
    )


# ---------------------------------------------------------------------------
# Level 3: named rubrics
# ---------------------------------------------------------------------------

DRIFT_EVIDENCE_RUBRIC = EvaluationRubric(
    name="drift_evidence",
    subject_description=(
        "an agent-filed drift report — a claim that a memory entry no longer reflects "
        "the live codebase. memory_summary is what the system recorded; evidence is what "
        "the agent found when checking the current code."
    ),
    passing_threshold=0.6,  # average score of 3 / 5 across both dimensions
    dimensions=(
        EvaluationDimension(
            name="Specificity",
            description=(
                "Does the evidence cite concrete, locatable facts — file names, function "
                "names, commit references, or exact behaviours? A 5 points to something "
                "a reviewer could verify in 30 seconds; a 1 is vague ('things have changed')."
            ),
        ),
        EvaluationDimension(
            name="Actionability",
            description=(
                "Is it clear what the human needs to do to resolve this report? A 5 "
                "tells them exactly whether to approve an update, dismiss as false alarm, "
                "or create a fix-it initiative; a 1 leaves the resolution path ambiguous."
            ),
        ),
    ),
)
