"""Initiatives: the dashboard feed, creation, and lifecycle transitions (BD-5 u4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.exceptions import ValidationError
from app.models import Initiative
from app.schemas import ArchiveInitiative, CreateInitiative
from app.store import SpecStore

router = APIRouter(tags=["initiatives"])


@router.get("/initiatives")
async def list_initiatives(store: Annotated[SpecStore, Depends(get_store)]) -> list[Initiative]:
    """The dashboard's feed: every initiative that has a spec (0004 a3)."""
    return await store.list_initiatives()


@router.post("/initiatives", status_code=201)
async def create_initiative(
    body: CreateInitiative,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Initiative:
    """Create an initiative under a project and scaffold its empty spec in one act (0004 a1).
    Every initiative belongs to a project (0010) — an unknown project_id -> 404."""
    if not body.title.strip():
        raise ValidationError("initiative title must not be empty")
    return await store.create_initiative(body.title, body.project_id)


@router.post("/initiatives/{initiative_id}/start-building", status_code=200)
async def start_building(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Initiative:
    """Manual 'start building' trigger (BD-5 u4): transition a draft initiative to building.
    Auto-transition also fires on first evidence submission via submit_evidence."""
    return await store.transition_to_building(initiative_id)


@router.post("/initiatives/{initiative_id}/revert-to-draft", status_code=200)
async def revert_to_draft(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Initiative:
    """Move a building initiative back to draft so its spec can be reshaped.
    Constraints, acceptance criteria, and discretion become editable again."""
    return await store.revert_to_draft(initiative_id)


@router.post("/initiatives/{initiative_id}/complete-without-learnings", status_code=200)
async def complete_without_learnings(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Initiative:
    """Escape hatch (BD-5 u4): complete a learning initiative without writing learnings.
    Caller must show the friction warning: 'Skipping reflection — nothing will be written to
    memory for this initiative.' Only valid from the learning state."""
    return await store.mark_complete_without_learnings(initiative_id)


@router.post("/initiatives/{initiative_id}/archive", status_code=200)
async def archive_initiative(
    initiative_id: str,
    body: ArchiveInitiative,
    store: Annotated[SpecStore, Depends(get_store)],
) -> dict:
    """Soft-archive an initiative (0013 follow-up). Reject from draft and Archive from
    building/complete share one mechanism — the spec, units, decisions, and memory are
    preserved; the dashboards just stop showing it. NotFoundError -> 404 centrally."""
    reason = (body.reason or "").strip() or "archived"
    await store.archive_initiative(initiative_id, reason)
    return {"id": initiative_id, "archived": True, "reason": reason}
