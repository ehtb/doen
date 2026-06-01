"""Learn-stage service (spec 0005 u2): assemble the outcome review, capture memory.

The review (a4) gathers intent, the resolved decisions (the calls + why), and the per-unit
verification outcomes so the human can judge what happened against what was intended.
Submitting (a5) writes one append-only memory row (embedded for the cross-initiative
flywheel) and marks the initiative done — a soft gate (constraint 8): incomplete units
don't block it.
"""

from __future__ import annotations

from typing import Any

from app.exceptions import InvalidStageTransition, NotFoundError, ValidationError
from app.providers.llm import StructuredLLM, get_advisor_llm
from app.schemas import LearnReview, OutcomeDraft
from app.store import SpecStore

LEARN_DRAFT_SYSTEM_PROMPT = """You are the Doen Advisor drafting the closing outcome for an \
initiative — for the human to correct and confirm before it is saved to memory. From the \
initiative's history (its intent, the decisions made and why, and how each work unit was judged), \
write an honest outcome the next initiative can learn from.

Return via the outcome tool:
- summary: a few sentences — what this initiative set out to do and what actually happened against \
its intent and acceptance criteria. Plain, honest prose. Note what shipped, what didn't, what \
changed along the way.
- learnings: the durable lessons worth carrying forward — what worked, what to do differently. A \
few crisp lines. This is what gets retrieved when shaping future initiatives, so make it \
transferable, not initiative-specific trivia.

Don't inflate. If units were left unverified or a decision proved wrong, say so plainly."""

LEARN_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What was intended vs. what happened."},
        "learnings": {"type": "string", "description": "Durable, transferable lessons."},
    },
    "required": ["summary", "learnings"],
}


async def learn_review(store: SpecStore, initiative_id: str) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    spec = await store.get_spec(initiative_id)
    return LearnReview(
        initiative=init,
        intent=spec.intent if spec else "",
        decisions=await store.list_decisions(initiative_id, status="resolved"),
        units=await store.list_units(initiative_id),
        memory=await store.list_memory(initiative_id),
    )


def _build_history(review: LearnReview) -> str:
    parts = [f"# INTENT\n{review.intent or '(none recorded)'}"]
    if review.decisions:
        parts.append(
            "# DECISIONS MADE (the calls + why):\n"
            + "\n".join(
                f"- {d.question}\n  chose: {d.chosen or '(unresolved)'}"
                + (f" — {d.rationale}" if d.rationale else "")
                for d in review.decisions
            )
        )
    if review.units:
        parts.append(
            "# WORK UNITS (how each landed):\n"
            + "\n".join(
                f"- [{u.status}] {u.title}"
                + (f" — verdict: {u.verdict.verdict}; {u.verdict.feedback}" if u.verdict else "")
                for u in review.units
            )
        )
    return "\n\n".join(parts)


async def draft_outcome(
    store: SpecStore, initiative_id: str, *, llm: StructuredLLM | None = None
) -> OutcomeDraft:
    """Draft a learn-stage outcome from the initiative's history (a8). The human corrects and
    confirms via submit_learn — this only drafts; nothing is written to memory here."""
    review = await learn_review(store, initiative_id)  # raises NotFoundError if absent
    llm = llm or get_advisor_llm()
    raw = await llm.complete_structured(
        system=LEARN_DRAFT_SYSTEM_PROMPT,
        user=_build_history(review),
        schema=LEARN_DRAFT_SCHEMA,
        schema_name="outcome",
    )
    return OutcomeDraft(
        summary=str(raw.get("summary", "")).strip(),
        learnings=str(raw.get("learnings", "")).strip(),
    )


async def submit_learn(
    store: SpecStore,
    initiative_id: str,
    *,
    summary: str,
    learnings: str | None,
    outcome: dict | None,
) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    if not summary.strip():
        raise ValidationError("the Learn stage needs a human-written outcome summary")
    await store.create_memory(initiative_id, summary.strip(), learnings, outcome)
    # Advance into Learn when we're one step away (from verify). The gate is soft — if the
    # initiative is further back than verify the memory is still captured; the stage move
    # stays with the human.
    if init.stage != "learn":
        try:
            await store.set_stage(initiative_id, "learn")
        except InvalidStageTransition:
            pass
    return await learn_review(store, initiative_id)
