"""Conversation rail endpoints (spec 0009 u1): persist + replay an initiative's history.

Thin: read the request, call the store/service, return. The Advisor's reply generation
(LLM) is u2 — this slice is storage + retrieval only (a4).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.models import Message
from app.schemas import AdvisorTurn, PostMessage
from app.services import advisor as advisor_service
from app.services import conversation as conversation_service
from app.store import SpecStore

router = APIRouter(tags=["conversation"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.get("/initiatives/{initiative_id}/messages")
async def list_messages(initiative_id: str, store: _Store) -> list[Message]:
    return await store.list_messages(initiative_id)


@router.post("/initiatives/{initiative_id}/messages", status_code=201)
async def post_message(initiative_id: str, body: PostMessage, store: _Store) -> Message:
    return await conversation_service.post_message(store, initiative_id, body.content)


@router.post("/initiatives/{initiative_id}/advisor", status_code=201)
async def advise(initiative_id: str, body: PostMessage, store: _Store) -> AdvisorTurn:
    """A conversational turn: persist the human message, generate the Advisor's stage-aware
    reply (with any proposal cards), and return both. The Advisor's reply generation (LLM)
    is u2; a failed call maps to 502 with no message persisted."""
    return await advisor_service.advise(store, initiative_id, body.content)
