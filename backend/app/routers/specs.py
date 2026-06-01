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
from app.schemas import AddItem, ConfirmAll, EditItem, ItemVersion
from app.services import authoring
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
