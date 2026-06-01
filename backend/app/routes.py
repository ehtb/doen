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
from uuid import uuid4

import asyncpg
from asyncpg.exceptions import ForeignKeyViolationError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.deps import get_pool, get_store
from app.store import (
    AcceptanceCriterion,
    Decision,
    InvalidTransition,
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
    appetite: str | None = None
    stage: Stage = "shape"


@router.post("/initiatives", status_code=201)
async def create_initiative(
    body: CreateInitiative,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> dict:
    initiative_id = f"init_{uuid4().hex[:12]}"
    row = await pool.fetchrow(
        """INSERT INTO initiatives (id, org_id, owner_id, appetite, stage)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING id, org_id, owner_id, appetite, stage, created_at""",
        initiative_id, DEV_ORG_ID, DEV_USER_ID, body.appetite, body.stage,
    )
    return dict(row)


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
