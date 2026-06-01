"""Verify-stage review (spec 0009 u5, a7): the Advisor weighs a submitted unit's evidence
against its acceptance criteria and posts preliminary notes to the rail for the human verifier.

These are notes, never a verdict — only the human judges (no self-approval). Auto-generated
when a unit is submitted (D1 -> b: the one proactive moment), best-effort so it never breaks
the submit. The executor's submission and the Advisor's review both live in Doen, visible to
the human — the agent-to-agent coordination of constraint 6, all through the shared spec.
"""

from __future__ import annotations

from typing import Any

from app.exceptions import NotFoundError, ValidationError
from app.models import CriterionReview, ReviewNotes, Spec, WorkUnit
from app.providers.llm import StructuredLLM, get_advisor_llm
from app.store import SpecStore

REVIEW_SYSTEM_PROMPT = """You are the Doen Advisor doing a PRELIMINARY review of a submitted work \
unit for the human verifier — who issues the actual verdict. You never approve work yourself. The \
executor has handed a unit back, mapping its output to the acceptance criteria with evidence. \
Weigh that evidence against each criterion independently and surface gaps, misalignments, and \
concerns so the human can judge quickly.

You're given the unit, the confirmed constraints that bind it, each acceptance criterion it must \
satisfy, and the executor's own claimed result + evidence per criterion.

Return via the review tool:
- summary: a few sentences — your overall read for the human. Where it looks solid, where you'd \
look harder.
- criteria: per criterion, your independent assessment — aligned (the evidence supports it), \
partial (only partly), gap (the evidence is missing or doesn't actually show it), or concern \
(something looks off) — with a short, specific note.
- concerns: cross-cutting issues — a crossed constraint, a missing test, a claim the evidence \
doesn't back. Empty if there are none.

Be specific and fair but skeptical: take the executor's evidence at face value only when it \
actually demonstrates the criterion. These are preliminary notes, not a verdict — the human decides."""

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Overall preliminary read for the human."},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "assessment": {
                        "type": "string",
                        "enum": ["aligned", "partial", "gap", "concern"],
                    },
                    "note": {"type": "string"},
                },
                "required": ["criterion", "assessment", "note"],
            },
        },
        "concerns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}


def _build_user_message(unit: WorkUnit, spec: Spec | None) -> str:
    by_id = {a.id: a for a in spec.acceptance} if spec else {}
    constraints = [c.text for c in spec.confirmed_constraints()] if spec else []
    sub = unit.submission
    assert sub is not None  # guarded by the caller
    results = {r.criterion_id: r for r in sub.criteria_results}

    parts = [
        f"# WORK UNIT\nTitle: {unit.title}\nScope: {unit.scope}",
        f"# EXECUTOR'S SUMMARY\n{sub.summary}",
    ]
    crit_lines: list[str] = []
    for cid in unit.criterion_ids:
        crit = by_id.get(cid)
        if crit is None:
            continue
        r = results.get(cid)
        claimed = (
            f"executor says: {r.result} — {r.evidence}" if r else "executor gave no result for this"
        )
        crit_lines.append(
            f"- {crit.text} [verify: {crit.verify.kind} — {crit.verify.detail}]\n  {claimed}"
        )
    # any results not tied to a known criterion id (defensive)
    parts.append(
        "# ACCEPTANCE CRITERIA + THE EXECUTOR'S EVIDENCE:\n"
        + ("\n".join(crit_lines) or "(no criteria mapped to this unit)")
    )
    if sub.artifacts:
        parts.append("# ARTIFACTS\n" + "\n".join(f"- {a}" for a in sub.artifacts))
    parts.append(
        "# CONFIRMED CONSTRAINTS (must not be crossed):\n"
        + ("\n".join(f"- {c}" for c in constraints) or "(none confirmed)")
    )
    return "\n\n".join(parts)


async def review_submission(
    store: SpecStore, unit_id: str, *, llm: StructuredLLM | None = None
) -> ReviewNotes:
    """Generate the Advisor's preliminary review of a submitted unit's evidence (a7)."""
    unit = await store.get_unit(unit_id)
    if unit is None:
        raise NotFoundError(f"no work unit {unit_id}")
    if unit.submission is None:
        raise ValidationError(f"unit {unit_id} has no submission to review")
    spec = await store.get_spec(unit.spec_id)

    llm = llm or get_advisor_llm()
    raw = await llm.complete_structured(
        system=REVIEW_SYSTEM_PROMPT,
        user=_build_user_message(unit, spec),
        schema=REVIEW_SCHEMA,
        schema_name="review",
    )
    criteria = [CriterionReview.model_validate(c) for c in raw.get("criteria") or []]
    return ReviewNotes(
        unit_id=unit_id,
        initiative_id=unit.spec_id,
        title=unit.title,
        summary=str(raw.get("summary", "")).strip(),
        criteria=criteria,
        concerns=[str(c) for c in raw.get("concerns") or []],
    )


def render_review(notes: ReviewNotes) -> str:
    """Format the review as the body of an advisor message on the rail."""
    lines = [f"Preliminary review of **{notes.title}** against its acceptance criteria.", ""]
    lines.append(notes.summary)
    if notes.criteria:
        lines.append("")
        for c in notes.criteria:
            lines.append(f"• [{c.assessment}] {c.criterion} — {c.note}")
    if notes.concerns:
        lines.append("")
        lines.append("Concerns:")
        lines += [f"• {c}" for c in notes.concerns]
    lines += ["", "These are preliminary notes — the verdict is yours."]
    return "\n".join(lines)


async def post_review(
    store: SpecStore, unit_id: str, *, llm: StructuredLLM | None = None
) -> ReviewNotes:
    """Review the submission and post it to the rail as an advisor message, with the structured
    notes in metadata for the UI. This is what the submit path triggers (D1 -> b)."""
    notes = await review_submission(store, unit_id, llm=llm)
    await store.append_message(
        notes.initiative_id, "advisor", render_review(notes), metadata={"review": notes.model_dump()}
    )
    return notes
