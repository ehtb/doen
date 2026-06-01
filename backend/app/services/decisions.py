"""Steering-rail service: validate and resolve an escalated decision.

A human issues the verdict; the store's resolve wakes the parked executor over Redis
pub/sub, resumes any unit blocked on it, and embeds the resolved reasoning into memory.
"""

from __future__ import annotations

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Decision
from app.store import SpecStore


async def resolve(
    store: SpecStore,
    decision_id: str,
    *,
    chosen: str,
    rationale: str,
    decided_by: str,
) -> Decision:
    d = await store.get_decision(decision_id)
    if d is None:
        raise NotFoundError(f"no decision {decision_id}")
    if d.status != "open":
        raise ConflictError(f"decision {decision_id} is already resolved")
    if chosen not in d.options:
        raise ValidationError(f"{chosen!r} is not one of the offered options")
    return await store.resolve_decision(decision_id, chosen, rationale, decided_by)
