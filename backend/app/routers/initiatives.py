"""Initiatives + lifecycle: the dashboard feed, creation, and stage progression."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.exceptions import ValidationError
from app.models import Initiative
from app.schemas import CreateInitiative, SetStage
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
    """Create an initiative and scaffold its empty spec in one act (0004 a1)."""
    if not body.title.strip():
        raise ValidationError("initiative title must not be empty")
    return await store.create_initiative(body.title)


@router.post("/initiatives/{initiative_id}/stage")
async def set_stage(
    initiative_id: str,
    body: SetStage,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Initiative:
    """Advance or retreat an initiative by one lifecycle step (0004 a4/a5); the spec's stage
    is kept in sync. A skip or arbitrary jump is rejected (InvalidStageTransition -> 422)."""
    return await store.set_stage(initiative_id, body.stage)
