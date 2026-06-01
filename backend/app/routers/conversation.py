"""Conversation rail endpoint (spec 0009 u1; spec uvama): the Advisor turn.

Conversations are browser-local now (spec uvama): the rail's history lives in the browser's
IndexedDB, not Postgres. There is no message read/write endpoint — the rail loads its own history
and POSTs a windowed slice with each turn. The backend assembles the prompt from that slice plus
spec + memory, replies, and persists nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.models import Message
from app.schemas import AdvisorReply, AdvisorRequest
from app.services import advisor as advisor_service
from app.store import SpecStore

router = APIRouter(tags=["conversation"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.post("/initiatives/{initiative_id}/advisor", status_code=201)
async def advise(initiative_id: str, body: AdvisorRequest, store: _Store) -> AdvisorReply:
    """A conversational turn: generate the Advisor's state-aware reply (with any proposal cards)
    from the human's message plus the windowed history the browser sent. Nothing is persisted —
    the frontend writes the reply into IndexedDB. A failed LLM call maps to 502."""
    history = [
        Message(initiative_id=initiative_id, role=m.role, content=m.content) for m in body.history
    ]
    reply = await advisor_service.advise(store, initiative_id, body.content, history)
    return AdvisorReply(message=reply)
