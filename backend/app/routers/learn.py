"""The Learn stage (0005 u2): review outcome vs. intent, capture memory, extract heuristics."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.models import Heuristic
from app.schemas import ConfirmHeuristics, HeuristicDraftResult, LearnReview, OutcomeDraft, SubmitLearn
from app.services import learn as learn_service
from app.store import SpecStore

router = APIRouter(tags=["learn"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.get("/initiatives/{initiative_id}/learn")
async def learn_review(initiative_id: str, store: _Store) -> LearnReview:
    return await learn_service.learn_review(store, initiative_id)


@router.post("/initiatives/{initiative_id}/learn/draft")
async def draft_outcome(initiative_id: str, store: _Store) -> OutcomeDraft:
    """The Advisor drafts the outcome from the initiative's history (0009 a8). The human edits
    and confirms it via POST .../learn, which is what writes to memory. An LLMError -> 502."""
    return await learn_service.draft_outcome(store, initiative_id)


@router.post("/initiatives/{initiative_id}/learn", status_code=201)
async def submit_learn(initiative_id: str, body: SubmitLearn, store: _Store) -> LearnReview:
    return await learn_service.submit_learn(
        store, initiative_id,
        summary=body.summary,
        learnings=body.learnings,
        outcome=body.outcome,
        rationale_claims=body.rationale_claims or None,
    )


# --- BD-17: heuristic extraction (after outcome is captured) -------------------------

@router.post("/initiatives/{initiative_id}/learn/heuristics/draft")
async def draft_heuristics(initiative_id: str, store: _Store) -> HeuristicDraftResult:
    """BD-17: Advisor proposes heuristics from the initiative's history. The human reviews
    and confirms via POST .../confirm — nothing is written to memory here."""
    return await learn_service.draft_heuristics(store, initiative_id)


@router.post("/initiatives/{initiative_id}/learn/heuristics/confirm", status_code=201)
async def confirm_heuristics(
    initiative_id: str, body: ConfirmHeuristics, store: _Store
) -> list[Heuristic]:
    """BD-17: Write human-confirmed heuristics to long-term memory. Skipping or abandoning
    this step leaves the heuristic count at zero (constraint item_a743fde4bc87)."""
    return await learn_service.confirm_heuristics(store, initiative_id, body)
