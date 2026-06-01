"""Learn-stage service (spec 0005 u2): assemble the outcome review, capture memory.

The review (a4) gathers intent, the resolved decisions (the calls + why), and the per-unit
verification outcomes so the human can judge what happened against what was intended.
Submitting (a5) writes one append-only memory row (embedded for the cross-initiative
flywheel) and marks the initiative done — a soft gate (constraint 8): incomplete units
don't block it.
"""

from __future__ import annotations

from app.exceptions import InvalidStageTransition, NotFoundError, ValidationError
from app.schemas import LearnReview
from app.store import SpecStore


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
