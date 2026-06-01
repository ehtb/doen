"""The steering rail: the open-decisions feed and the human's resolution."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.models import Decision
from app.schemas import ResolveDecision
from app.services import decisions as decisions_service
from app.store import SpecStore

router = APIRouter(tags=["decisions"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.get("/initiatives/{initiative_id}/decisions")
async def list_open_decisions(initiative_id: str, store: _Store) -> list[Decision]:
    return await store.list_open_decisions(initiative_id)


@router.post("/decisions/{decision_id}/resolve")
async def resolve_decision(decision_id: str, body: ResolveDecision, store: _Store) -> Decision:
    """The human's verdict; wakes any parked executor over Redis pub/sub."""
    return await decisions_service.resolve(
        store, decision_id,
        chosen=body.chosen, rationale=body.rationale, decided_by=body.decided_by,
    )
