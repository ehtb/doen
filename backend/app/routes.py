"""HTTP surface for the spec slice (u2), the steering rail, and spec authoring.

Endpoints:
  POST  /initiatives                          — create the parent row a spec hangs off of.
  PUT   /specs/{id}                           — create-or-update the living spec; 409 on stale version.
  GET   /specs/{id}                           — the whole spec in one call (warm reads from Redis).
  GET   /initiatives/{id}/decisions           — the rail's feed: an initiative's open decisions.
  POST  /decisions/{id}/resolve               — the human verdict; wakes any parked executor.
  POST  /specs/{id}/items                     — author a new item (human-authored → confirmed).
  POST  /specs/{id}/items/{item_id}/confirm   — confirm a proposed item; it begins to govern.
  PATCH /specs/{id}/items/{item_id}           — edit an item's text; reverts it to proposed.
  POST  /specs/{id}/items/{item_id}/retire    — soft-retire an item; it stops governing, stays in the doc.

Authoring goes through SpecStore.save_spec, so every write respects `version` as the
optimistic lock — a human edit never silently clobbers a concurrent change.
"""

from __future__ import annotations

from typing import Annotated, Literal

import asyncpg
from asyncpg.exceptions import ForeignKeyViolationError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import DEV_USER_ID
from app.deps import get_pool, get_store
from app.llm import LLMError
from app.shaping import shape_spec
from app.store import (
    AcceptanceCriterion,
    Decision,
    Initiative,
    InvalidStageTransition,
    InvalidTransition,
    Memory,
    Spec,
    SpecItem,
    SpecStore,
    Stage,
    StaleSpecError,
    Verify,
    WorkUnit,
    _now,
)

router = APIRouter()


class CreateInitiative(BaseModel):
    title: str


@router.get("/initiatives")
async def list_initiatives(
    store: Annotated[SpecStore, Depends(get_store)],
) -> list[Initiative]:
    """The dashboard's feed: every initiative that has a spec (0004 a3)."""
    return await store.list_initiatives()


@router.post("/initiatives", status_code=201)
async def create_initiative(
    body: CreateInitiative,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Initiative:
    """Create an initiative and scaffold its empty spec in one act (0004 a1): a unique
    slug from the title, and a new spec at version 0, stage=discover."""
    if not body.title.strip():
        raise HTTPException(422, "initiative title must not be empty")
    return await store.create_initiative(body.title)


class SetStage(BaseModel):
    stage: Stage  # the target stage — must be one lifecycle step from the current one


@router.post("/initiatives/{initiative_id}/stage")
async def set_stage(
    initiative_id: str,
    body: SetStage,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Initiative:
    """Advance or retreat an initiative by one lifecycle step (0004 a4/a5); the spec's
    stage is kept in sync. A skip or arbitrary jump is rejected."""
    try:
        return await store.set_stage(initiative_id, body.stage)
    except KeyError:
        raise HTTPException(404, f"no initiative {initiative_id}")
    except InvalidStageTransition as e:
        raise HTTPException(422, str(e))


@router.put("/specs/{initiative_id}")
async def save_spec(
    initiative_id: str,
    spec: Spec,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    if spec.initiative_id != initiative_id:
        raise HTTPException(400, "initiative_id in path and body must match")
    try:
        return await store.save_spec(spec)
    except StaleSpecError as e:
        raise HTTPException(409, str(e))
    except ForeignKeyViolationError:
        raise HTTPException(404, f"initiative {initiative_id} does not exist")


@router.get("/specs/{initiative_id}")
async def read_spec(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise HTTPException(404, f"no spec for initiative {initiative_id}")
    return spec


# --- steering rail: the human counterpart to raise_decision / wait_for_decision ---
class ResolveDecision(BaseModel):
    chosen: str
    rationale: str
    decided_by: str = DEV_USER_ID  # single dev user this slice; auth replaces this


@router.get("/initiatives/{initiative_id}/decisions")
async def list_open_decisions(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> list[Decision]:
    return await store.list_open_decisions(initiative_id)


@router.post("/decisions/{decision_id}/resolve")
async def resolve_decision(
    decision_id: str,
    body: ResolveDecision,
    store: Annotated[SpecStore, Depends(get_store)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> Decision:
    row = await pool.fetchrow(
        "SELECT payload, status FROM decisions WHERE id = $1", decision_id
    )
    if row is None:
        raise HTTPException(404, f"no decision {decision_id}")
    if row["status"] != "open":
        raise HTTPException(409, f"decision {decision_id} is already resolved")
    d = Decision.model_validate_json(row["payload"])
    if body.chosen not in d.options:
        raise HTTPException(422, f"{body.chosen!r} is not one of the offered options")
    # A human issues the verdict; resolve_decision wakes the parked executor over the
    # existing Redis pub-sub path — no second wake mechanism.
    return await store.resolve_decision(
        decision_id, body.chosen, body.rationale, body.decided_by
    )


# --- spec authoring: confirm / add / edit / retire items on the living spec ---------
# The `version` on each request is the optimistic lock surfaced to the editor: it is the
# version the human last saw. save_spec re-checks it under a row lock, so a stale edit is
# rejected (409) rather than clobbering a concurrent change.
Section = Literal["constraints", "discretion", "acceptance"]


class AddItem(BaseModel):
    section: Section
    text: str
    version: int
    verify: Verify | None = None  # required iff section == "acceptance"


class EditItem(BaseModel):
    text: str
    version: int


class ItemVersion(BaseModel):
    version: int


class ConfirmAll(BaseModel):
    version: int
    section: Section | None = None  # None = every section


def _find_item(spec: Spec, item_id: str) -> SpecItem | None:
    for section in ("constraints", "discretion", "acceptance"):
        for it in getattr(spec, section):
            if it.id == item_id:
                return it
    return None


async def _load_at(store: SpecStore, initiative_id: str, expected_version: int) -> Spec:
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise HTTPException(404, f"no spec for initiative {initiative_id}")
    if spec.version != expected_version:
        raise HTTPException(
            409, f"stale version (spec is at v{spec.version}, you have v{expected_version})"
        )
    return spec


async def _save(store: SpecStore, spec: Spec) -> Spec:
    try:
        return await store.save_spec(spec)
    except StaleSpecError as e:
        raise HTTPException(409, str(e))  # lost a race between our read and write


@router.post("/specs/{initiative_id}/items")
async def add_item(
    initiative_id: str,
    body: AddItem,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    if not body.text.strip():
        raise HTTPException(422, "item text must not be empty")
    if body.section == "acceptance" and body.verify is None:
        raise HTTPException(422, "an acceptance item needs a verify {kind, detail}")

    spec = await _load_at(store, initiative_id, body.version)
    # A human authoring an item is itself the act of confirmation (decision dec_726cb3ab8f15):
    # it is born `human` + `confirmed`, governing immediately.
    fields = dict(text=body.text, provenance="human", status="confirmed", confirmed_at=_now())
    item: SpecItem = (
        AcceptanceCriterion(verify=body.verify, **fields)
        if body.section == "acceptance"
        else SpecItem(**fields)
    )
    getattr(spec, body.section).append(item)
    return await _save(store, spec)


@router.post("/specs/{initiative_id}/items/{item_id}/confirm")
async def confirm_item(
    initiative_id: str,
    item_id: str,
    body: ItemVersion,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    spec = await _load_at(store, initiative_id, body.version)
    it = _find_item(spec, item_id)
    if it is None:
        raise HTTPException(404, f"no item {item_id} on this spec")
    if it.status != "proposed":
        raise HTTPException(422, f"only a proposed item can be confirmed (it is {it.status})")
    it.status = "confirmed"
    it.confirmed_at = _now()
    # Confirming the AI's exact wording records the human's endorsement in the provenance.
    if it.provenance == "ai_proposed":
        it.provenance = "ai_confirmed_by_human"
    return await _save(store, spec)


@router.patch("/specs/{initiative_id}/items/{item_id}")
async def edit_item(
    initiative_id: str,
    item_id: str,
    body: EditItem,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    if not body.text.strip():
        raise HTTPException(422, "item text must not be empty")
    spec = await _load_at(store, initiative_id, body.version)
    it = _find_item(spec, item_id)
    if it is None:
        raise HTTPException(404, f"no item {item_id} on this spec")
    if it.status == "retired":
        raise HTTPException(422, "cannot edit a retired item")
    # Editing the text is substantive: it reverts to `proposed` and must be re-confirmed
    # before it governs again (decision dec_557ca094fe3e). The human now owns the wording.
    it.text = body.text
    it.status = "proposed"
    it.confirmed_at = None
    it.provenance = "human"
    return await _save(store, spec)


@router.post("/specs/{initiative_id}/items/{item_id}/retire")
async def retire_item(
    initiative_id: str,
    item_id: str,
    body: ItemVersion,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    spec = await _load_at(store, initiative_id, body.version)
    it = _find_item(spec, item_id)
    if it is None:
        raise HTTPException(404, f"no item {item_id} on this spec")
    if it.status == "retired":
        raise HTTPException(422, "item is already retired")
    # Soft state: it stays in the document for history but no longer governs an executor.
    it.status = "retired"
    return await _save(store, spec)


@router.post("/specs/{initiative_id}/confirm-all")
async def confirm_all(
    initiative_id: str,
    body: ConfirmAll,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    """Accept a draft in one gesture — confirm every proposed item at once, or just one
    section's (body.section). The common path: the human reads the AI's draft, corrects
    the exceptions (edit / retire), then confirms the rest as a batch instead of one
    micro-decision per item."""
    spec = await _load_at(store, initiative_id, body.version)
    sections = (body.section,) if body.section else ("constraints", "discretion", "acceptance")
    confirmed = 0
    for section in sections:
        for it in getattr(spec, section):
            if it.status == "proposed":
                it.status = "confirmed"
                it.confirmed_at = _now()
                if it.provenance == "ai_proposed":
                    it.provenance = "ai_confirmed_by_human"
                confirmed += 1
    if confirmed == 0:
        return spec  # nothing proposed; don't bump the version for a no-op
    return await _save(store, spec)


# --- work units (spec 0003): a human confirms proposed units and judges submissions ---
# Units are NOT under the spec's optimistic lock (constraint 1) — they're a separate table
# that churns at its own rate, so these endpoints carry no `version`. Units are created by
# the executor over MCP (propose_unit); there is deliberately no HTTP create-or-confirm path
# for an agent — confirming and judging are human acts.
class UnitVerdict(BaseModel):
    verdict: Literal["approved", "changes_requested"]
    feedback: str = ""
    decided_by: str = DEV_USER_ID  # single dev user this slice; auth replaces this


@router.get("/specs/{initiative_id}/units")
async def list_units(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
    status: str | None = None,
) -> list[WorkUnit]:
    return await store.list_units(initiative_id, status)


@router.post("/units/{unit_id}/confirm")
async def confirm_unit(
    unit_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> WorkUnit:
    try:
        return await store.confirm_unit(unit_id)
    except KeyError:
        raise HTTPException(404, f"no work unit {unit_id}")
    except InvalidTransition as e:
        raise HTTPException(422, str(e))  # only a proposed unit can be confirmed


@router.post("/units/{unit_id}/verdict")
async def record_verdict(
    unit_id: str,
    body: UnitVerdict,
    store: Annotated[SpecStore, Depends(get_store)],
) -> WorkUnit:
    try:
        return await store.record_verdict(unit_id, body.verdict, body.feedback, body.decided_by)
    except KeyError:
        raise HTTPException(404, f"no work unit {unit_id}")
    except InvalidTransition as e:
        raise HTTPException(422, str(e))  # a verdict is legal only on a submitted unit


# --- learn stage (spec 0005 u2): review outcome vs. intent, capture memory ----------
# Closing the lifecycle. The review (a4) gathers the original intent, the resolved
# decisions (the calls + why), and the per-unit verification outcomes so the human can
# judge what happened against what was intended. Submitting (a5) writes one append-only
# memory row, embedded for the cross-initiative flywheel, and marks the initiative done.
class LearnReview(BaseModel):
    initiative: Initiative
    intent: str
    decisions: list[Decision]  # resolved only — the reasoning behind what shipped
    units: list[WorkUnit]
    memory: list[Memory]


class SubmitLearn(BaseModel):
    summary: str
    learnings: str | None = None
    outcome: dict | None = None


async def _learn_review(store: SpecStore, initiative_id: str) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise HTTPException(404, f"no initiative {initiative_id}")
    spec = await store.get_spec(initiative_id)
    return LearnReview(
        initiative=init,
        intent=spec.intent if spec else "",
        decisions=await store.list_decisions(initiative_id, status="resolved"),
        units=await store.list_units(initiative_id),
        memory=await store.list_memory(initiative_id),
    )


@router.get("/initiatives/{initiative_id}/learn")
async def learn_review(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> LearnReview:
    return await _learn_review(store, initiative_id)


@router.post("/initiatives/{initiative_id}/learn", status_code=201)
async def submit_learn(
    initiative_id: str,
    body: SubmitLearn,
    store: Annotated[SpecStore, Depends(get_store)],
) -> LearnReview:
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise HTTPException(404, f"no initiative {initiative_id}")
    if not body.summary.strip():
        raise HTTPException(422, "the Learn stage needs a human-written outcome summary")
    await store.create_memory(initiative_id, body.summary.strip(), body.learnings, body.outcome)
    # Mark complete: advance into Learn when we're one step away (from verify). The gate is
    # soft (constraint 8) — incomplete units don't block this. If the initiative is further
    # back than verify the memory is still captured; the stage move stays with the human.
    if init.stage != "learn":
        try:
            await store.set_stage(initiative_id, "learn")
        except InvalidStageTransition:
            pass
    return await _learn_review(store, initiative_id)


# --- AI-assisted shaping (spec 0006 u3): description -> proposed spec ----------------
# get_context feeds memory priors, the LLM drafts, and the proposals land as proposed items
# the human confirms through the existing 0002 flow. A failed LLM call leaves the spec
# untouched (constraint 7 / a6). Re-shaping refreshes the proposed draft but never touches
# confirmed items, and only sets intent when it's still blank.
class ShapeWithAI(BaseModel):
    description: str


@router.post("/specs/{initiative_id}/shape", status_code=201)
async def shape_with_ai(
    initiative_id: str,
    body: ShapeWithAI,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    if not body.description.strip():
        raise HTTPException(422, "a description is required to shape a spec")
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise HTTPException(404, f"no spec for initiative {initiative_id}")
    try:
        result = await shape_spec(store, initiative_id, body.description)
    except LLMError as e:
        # surfaced cleanly; save_spec is never reached, so the spec is unchanged (a6).
        raise HTTPException(502, f"shaping failed: {e}")

    keep = lambda items: [i for i in items if i.status != "proposed"]  # noqa: E731
    spec.constraints = keep(spec.constraints) + result.constraints
    spec.discretion = keep(spec.discretion) + result.discretion
    spec.acceptance = keep(spec.acceptance) + result.acceptance
    if not spec.intent.strip() and result.intent:
        spec.intent = result.intent
    return await store.save_spec(spec)
