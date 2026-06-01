"""Conversation service (spec 0009 u1): persist rail turns, assemble the Advisor's context.

This unit is the substrate the Advisor (u2) runs on. It does NOT call the LLM — it stores
the human's turns and assembles the explicit, bounded context an Advisor call will read
(constraint 1): a recent-message window + the current spec + relevant memory. Keeping the
assembly here, framework-agnostic and LLM-free, makes the windowing testable on its own and
reusable from both the rail endpoint and the MCP briefing (u4).
"""

from __future__ import annotations

from app.exceptions import NotFoundError, ValidationError
from app.models import ConversationContext, Message, Spec
from app.store import MESSAGE_WINDOW, SpecStore


async def post_message(store: SpecStore, initiative_id: str, content: str) -> Message:
    """Persist a human turn on the rail. The role is fixed server-side — a client never
    forges an Advisor message; those are appended by the Advisor service (u2)."""
    if (await store.get_initiative(initiative_id)) is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    if not content.strip():
        raise ValidationError("a message needs content")
    return await store.append_message(initiative_id, "human", content.strip())


async def assemble_context(
    store: SpecStore,
    initiative_id: str,
    *,
    window: int = MESSAGE_WINDOW,
    memory_limit: int = 5,
    pending_human: str | None = None,
) -> ConversationContext:
    """Build the bounded context for an Advisor turn (constraint 1). Memory is retrieved off
    the most recent human turn (falling back to the spec's intent/title) so the hits are
    relevant to where the conversation is, not the initiative as a whole.

    `pending_human` is the not-yet-persisted turn the Advisor is about to answer: it's
    appended to the window (so it's the latest turn the LLM sees) and anchors the memory
    query. The Advisor only persists the exchange after a successful reply, so the turn
    isn't in the store yet — keeping a failed generation from leaving an orphan message."""
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    spec = await store.get_spec(initiative_id)
    messages = await store.list_messages(initiative_id, limit=window)
    if pending_human:
        pending = Message(initiative_id=initiative_id, role="human", content=pending_human)
        messages = (messages + [pending])[-window:]
    query = _memory_query(messages, spec)
    memory = await store.get_context(query, limit=memory_limit) if query.strip() else []
    return ConversationContext(initiative=init, spec=spec, messages=messages, memory=memory)


def _memory_query(messages: list[Message], spec: Spec | None) -> str:
    """What to retrieve relevant memory against: the latest human turn, else the spec's
    intent, else its title. Empty if there's nothing to anchor on (get_context returns [])."""
    for m in reversed(messages):
        if m.role == "human":
            return m.content
    if spec and spec.intent:
        return spec.intent
    return spec.title if spec else ""
