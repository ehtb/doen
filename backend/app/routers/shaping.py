"""AI-assisted shaping (0006): a description in, a proposed spec out.

The shaping service fetches memory priors, calls the LLM, parses the proposal, and persists
it as proposed items the human confirms via the 0002 authoring flow. A failed LLM call
(LLMError) is mapped to 502 by the handlers, with the spec left untouched (constraint 7).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
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
