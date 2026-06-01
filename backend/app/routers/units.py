"""Work units (0003): the human confirms proposed units and judges submissions.

Units are created by the executor over MCP (propose_unit); there is deliberately no HTTP
create-or-confirm path for an agent — confirming and judging are human acts. NotFoundError
and InvalidTransition from the store are mapped to 404 / 422 by the handlers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.models import WorkUnit
from app.schemas import UnitVerdict
from app.store import SpecStore

router = APIRouter(tags=["work-units"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.get("/specs/{initiative_id}/units")
async def list_units(
    initiative_id: str, store: _Store, status: str | None = None
) -> list[WorkUnit]:
    return await store.list_units(initiative_id, status)


@router.post("/units/{unit_id}/confirm")
async def confirm_unit(unit_id: str, store: _Store) -> WorkUnit:
    return await store.confirm_unit(unit_id)


@router.post("/units/{unit_id}/reject")
async def reject_unit(unit_id: str, store: _Store) -> WorkUnit:
    """Reject a proposed unit (0011 a6): delete it and log to the rail (D1 -> c). Only a
    proposed unit is rejectable (ValidationError -> 422). Returns the removed unit."""
    return await store.reject_unit(unit_id)


@router.post("/units/{unit_id}/verdict")
async def record_verdict(unit_id: str, body: UnitVerdict, store: _Store) -> WorkUnit:
    return await store.record_verdict(unit_id, body.verdict, body.feedback, body.decided_by)
