"""Learn service: assemble the outcome review and capture memory.

The review gathers intent and the resolved decisions (the calls + why) so the human can
reflect on what happened. Submitting writes one append-only memory row embedded for the
cross-initiative flywheel.
"""

from __future__ import annotations

from typing import Any

from app.exceptions import NotFoundError, ValidationError
from app.providers.llm import StructuredLLM, get_advisor_llm
from app.schemas import LearnReview, OutcomeDraft, RationaleClaim
from app.store import SpecStore

LEARN_DRAFT_SYSTEM_PROMPT = """You are the Doen Advisor drafting the closing outcome for an \
initiative — for the human to correct and confirm before it is saved to memory. From the \
initiative's history (its intent, the decisions made and why, and the acceptance criteria \
and their verification outcomes), write an honest outcome the next initiative can learn from.

Return via the outcome tool:
- summary: a few sentences — what this initiative set out to do and what actually happened against \
its intent and acceptance criteria. Plain, honest prose. Note what shipped, what didn't, what \
changed along the way.
- learnings: the durable lessons worth carrying forward — what worked, what to do differently. A \
few crisp lines. This is what gets retrieved when shaping future initiatives, so make it \
transferable, not initiative-specific trivia.
- rationale_claims: a list of specific cause-effect claims traceable to the record. Each claim \
MUST cite a real source_id from the decisions or criteria listed below (a decision id like \
dec_abc123, or a criterion id like item_abc123). NEVER fabricate an id or reference something \
not in the record. If you have nothing traceable, return an empty list. Each claim is:
  - claim: one sentence stating a concrete cause and its effect
  - source_id: the exact id from the record it traces to
  - source_type: "decision" or "criterion"

Don't inflate. If units were left unverified or a decision proved wrong, say so plainly."""

LEARN_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What was intended vs. what happened."},
        "learnings": {"type": "string", "description": "Durable, transferable lessons."},
        "rationale_claims": {
            "type": "array",
            "description": "Cause-effect claims each traceable to a specific decision or criterion id in the record.",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "One-sentence cause-effect statement."},
                    "source_id": {"type": "string", "description": "The exact id (dec_… or item_…) from the record."},
                    "source_type": {"type": "string", "enum": ["decision", "criterion"]},
                },
                "required": ["claim", "source_id", "source_type"],
            },
        },
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
        memory=await store.list_memory(initiative_id),
    )


def _build_history(review: LearnReview, spec=None) -> str:
    """Build the history context for the Advisor, including record IDs so the LLM can
    produce traceable rationale claims (BD-13)."""
    parts = [f"# INTENT\n{review.intent or '(none recorded)'}"]
    if review.decisions:
        parts.append(
            "# DECISIONS MADE (id · question · outcome):\n"
            + "\n".join(
                f"- id={d.id}  question: {d.question}\n"
                f"  chose: {d.chosen or '(unresolved)'}"
                + (f" — {d.rationale}" if d.rationale else "")
                for d in review.decisions
            )
        )
    if spec is not None and spec.acceptance:
        confirmed = [c for c in spec.acceptance if c.status == "confirmed"]
        if confirmed:
            parts.append(
                "# ACCEPTANCE CRITERIA (id · text · verification outcome):\n"
                + "\n".join(
                    f"- id={c.id}  {c.text}\n"
                    f"  status={c.verification_status}"
                    + (f" | feedback: {c.feedback}" if c.feedback else "")
                    for c in confirmed
                )
            )
    return "\n\n".join(parts)


def _parse_rationale_claims(raw_claims: list[Any], valid_ids: set[str]) -> list[RationaleClaim]:
    """Parse and validate rationale claims from LLM output — only keep claims whose
    source_id matches an actual record entry (BD-13 constraint: no fabricated IDs)."""
    result = []
    for item in raw_claims or []:
        try:
            c = RationaleClaim(
                claim=str(item.get("claim", "")).strip(),
                source_id=str(item.get("source_id", "")).strip(),
                source_type=item.get("source_type", "decision"),
            )
            if not c.claim or not c.source_id:
                continue
            if c.source_id not in valid_ids:
                continue  # reject fabricated IDs — constraint item_ed83f4886d2c
            result.append(c)
        except Exception:
            continue
    return result


async def draft_outcome(
    store: SpecStore, initiative_id: str, *, llm: StructuredLLM | None = None
) -> OutcomeDraft:
    """BD-13 enriched draft: outcome + structured rationale claims with record-traceable IDs.
    The human corrects and confirms via submit_learn — nothing is written to memory here."""
    review = await learn_review(store, initiative_id)  # raises NotFoundError if absent
    spec = await store.get_spec(initiative_id)
    llm = llm or get_advisor_llm()
    raw = await llm.complete_structured(
        system=LEARN_DRAFT_SYSTEM_PROMPT,
        user=_build_history(review, spec),
        schema=LEARN_DRAFT_SCHEMA,
        schema_name="outcome",
    )

    # Build the set of valid record IDs the LLM is allowed to cite.
    decision_ids = {d.id for d in review.decisions}
    criterion_ids = {c.id for c in (spec.acceptance if spec else [])}
    valid_ids = decision_ids | criterion_ids

    claims = _parse_rationale_claims(raw.get("rationale_claims") or [], valid_ids)

    return OutcomeDraft(
        summary=str(raw.get("summary", "")).strip(),
        learnings=str(raw.get("learnings", "")).strip(),
        rationale_claims=claims,
    )


async def submit_learn(
    store: SpecStore,
    initiative_id: str,
    *,
    summary: str,
    learnings: str | None,
    outcome: dict | None,
    rationale_claims: list[RationaleClaim] | None = None,
) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    if not summary.strip():
        raise ValidationError("capturing the outcome needs a human-written summary")
    # BD-13: merge human-confirmed rationale claims into the outcome dict so they are
    # stored with the memory record and retrievable for future initiatives.
    if rationale_claims:
        outcome = {**(outcome or {}), "rationale_claims": [c.model_dump() for c in rationale_claims]}
    await store.create_memory(initiative_id, summary.strip(), learnings, outcome)
    return await learn_review(store, initiative_id)
