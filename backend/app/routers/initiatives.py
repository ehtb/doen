"""Initiatives: the dashboard feed and creation. The lifecycle state is inferred from the work
units + learn record (0011), never advanced by hand — so there is no stage endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.exceptions import ValidationError
from app.models import Initiative
from app.schemas import CreateInitiative
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
