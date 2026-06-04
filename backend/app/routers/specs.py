"""The living spec: read/write the whole doc, and author items (0002).

Authoring is delegated to the authoring service, which respects `version` as the
optimistic lock — a human edit never silently clobbers a concurrent change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_store
from app.exceptions import NotFoundError
from app.models import Spec
from app.schemas import AddItem, CriterionVerdictBody, ConfirmAll, EditItem, ItemVersion, SubmitCriterionEvidence
from app.services import authoring, review
from app.store import SpecStore

router = APIRouter(tags=["specs"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.put("/specs/{initiative_id}")
async def save_spec(initiative_id: str, spec: Spec, store: _Store) -> Spec:
    if spec.initiative_id != initiative_id:
        raise HTTPException(400, "initiative_id in path and body must match")
    # StaleSpecError -> 409 and ForeignKeyViolationError -> 404 are mapped by the handlers.
    return await store.save_spec(spec)


@router.get("/specs/{initiative_id}")
async def read_spec(initiative_id: str, store: _Store) -> Spec:
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {initiative_id}")
    return spec


@router.post("/specs/{initiative_id}/items")
async def add_item(initiative_id: str, body: AddItem, store: _Store) -> Spec:
    return await authoring.add_item(
        store, initiative_id,
        section=body.section, text=body.text, version=body.version, verify=body.verify,
        provenance=body.provenance,
    )


@router.post("/specs/{initiative_id}/items/{item_id}/confirm")
async def confirm_item(initiative_id: str, item_id: str, body: ItemVersion, store: _Store) -> Spec:
    return await authoring.confirm_item(store, initiative_id, item_id, body.version)


@router.patch("/specs/{initiative_id}/items/{item_id}")
async def edit_item(initiative_id: str, item_id: str, body: EditItem, store: _Store) -> Spec:
    return await authoring.edit_item(
        store, initiative_id, item_id, text=body.text, version=body.version
    )


@router.post("/specs/{initiative_id}/items/{item_id}/retire")
async def retire_item(initiative_id: str, item_id: str, body: ItemVersion, store: _Store) -> Spec:
    return await authoring.retire_item(store, initiative_id, item_id, body.version)


@router.post("/specs/{initiative_id}/items/{item_id}/reject")
async def reject_item(initiative_id: str, item_id: str, body: ItemVersion, store: _Store) -> Spec:
    """Reject a proposed item (0011 a6): remove it from the spec and log the rejection to the
    rail (D1 -> c). Only a proposed item is rejectable (ValidationError -> 422)."""
    return await authoring.reject_item(store, initiative_id, item_id, body.version)


@router.post("/specs/{initiative_id}/confirm-all")
async def confirm_all(initiative_id: str, body: ConfirmAll, store: _Store) -> Spec:
    return await authoring.confirm_all(
        store, initiative_id, version=body.version, section=body.section
    )


@router.post("/specs/{initiative_id}/batch-approve-confident")
async def batch_approve_confident(
    initiative_id: str, body: ItemVersion, store: _Store
) -> Spec:
    """BD-14: confirm all proposed items the Advisor classified as confident in one action."""
    return await authoring.batch_approve_confident(store, initiative_id, version=body.version)


@router.post("/specs/{initiative_id}/criteria/{criterion_id}/evidence")
async def submit_criterion_evidence(
    initiative_id: str, criterion_id: str, body: SubmitCriterionEvidence, store: _Store
) -> Spec:
    """BD-15: submit evidence against a single criterion from the conversation rail.
    Sets verification_status to 'evidence_submitted' — identical outcome to the MCP
    submit_evidence tool (BD-5), enabling research initiatives to complete their full
    lifecycle without an MCP connection."""
    spec = await store.submit_evidence(
        initiative_id, [{"criterion_id": criterion_id, "evidence": body.evidence}]
    )
    # BD-14: schedule synthesis in the background via the store's tracked task pool —
    # same pattern as embed_decision/embed_memory: reference kept, retried 3×, logged
    # on failure, drained cleanly on shutdown.
    store._spawn(lambda: review.generate_verification_synthesis(store, initiative_id))
    return spec


@router.post("/specs/{initiative_id}/criteria/{criterion_id}/verdict")
async def criterion_verdict(
    initiative_id: str, criterion_id: str, body: CriterionVerdictBody, store: _Store
) -> Spec:
    """Human approves or requests changes on a criterion that has evidence (BD-5 u3)."""
    return await store.record_criterion_verdict(
        initiative_id, criterion_id, body.verdict, body.feedback
    )
