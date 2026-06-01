"""The Learn stage (0005 u2): review outcome vs. intent, capture memory."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.schemas import LearnReview, SubmitLearn
from app.services import learn as learn_service
from app.store import SpecStore

router = APIRouter(tags=["learn"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.get("/initiatives/{initiative_id}/learn")
async def learn_review(initiative_id: str, store: _Store) -> LearnReview:
    return await learn_service.learn_review(store, initiative_id)


@router.post("/initiatives/{initiative_id}/learn", status_code=201)
async def submit_learn(initiative_id: str, body: SubmitLearn, store: _Store) -> LearnReview:
    return await learn_service.submit_learn(
        store, initiative_id,
        summary=body.summary, learnings=body.learnings, outcome=body.outcome,
    )
