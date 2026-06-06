"""AI-assisted shaping (0006): a description in, a proposed spec out.

The shaping service fetches memory priors, calls the LLM, parses the proposal, and persists
it as proposed items the human confirms via the 0002 authoring flow. A failed LLM call
(LLMError) is mapped to 502 by the handlers, with the spec left untouched (constraint 7).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends

from app.database import get_store
from app.exceptions import NotFoundError
from app.models import Spec
from app.schemas import ShapeWithAI
from app.services import shaping as shaping_service
from app.store import SpecStore

router = APIRouter(tags=["shaping"])


@router.post("/specs/{initiative_id}/shape", status_code=201)
async def shape_with_ai(
    initiative_id: str,
    body: ShapeWithAI,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    return await shaping_service.shape_and_persist(store, initiative_id, body.description)


@router.post("/specs/{initiative_id}/retry-shaping", status_code=200)
async def retry_shaping(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
    background_tasks: BackgroundTasks,
) -> Spec:
    """Re-queue async shaping for an initiative whose spec has shaping_status='error'.
    Marks the spec 'pending' immediately and returns; the LLM fill runs in the background
    using the original description stored at creation time (falling back to the title)."""
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {initiative_id}")
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    description = spec.original_description or spec.title or initiative_id
    spec.shaping_status = "pending"
    spec = await store.save_spec(spec)
    background_tasks.add_task(
        shaping_service.fill_spec_from_description,
        store, initiative_id, description,
        project_id=init.project_id, initiative_type=init.initiative_type,
    )
    return spec
