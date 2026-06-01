"""Conversation service (spec 0009 u1): persist rail turns, assemble the Advisor's context.

This unit is the substrate the Advisor (u2) runs on. It does NOT call the LLM — it stores
the human's turns and assembles the explicit, bounded context an Advisor call will read
(constraint 1): a recent-message window + the current spec + relevant memory. Keeping the
assembly here, framework-agnostic and LLM-free, makes the windowing testable on its own and
reusable from both the rail endpoint and the MCP briefing (u4).
"""

from __future__ import annotations

from typing import Any

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
    # 0010 constraint 4: memory retrieval is project-scoped — project-first, global fallback.
    # Every initiative belongs to a project, so project_id is always set.
    memory = (
        await store.get_context(query, limit=memory_limit, project_id=init.project_id)
        if query.strip()
        else []
    )
    # 0010 constraint 2: widen the context to the whole project — the sibling summaries the
    # Advisor reasons across.
    project = await store.get_project_context(init.project_id, exclude=initiative_id)
    return ConversationContext(
        initiative=init, spec=spec, messages=messages, memory=memory, project=project
    )


def _memory_query(messages: list[Message], spec: Spec | None) -> str:
    """What to retrieve relevant memory against: the latest human turn, else the spec's
    intent, else its title. Empty if there's nothing to anchor on (get_context returns [])."""
    for m in reversed(messages):
        if m.role == "human":
            return m.content
    if spec and spec.intent:
        return spec.intent
    return spec.title if spec else ""


# --- 0013 u5: enrich the executor's view of a spec -----------------------------------
def _latest_advisor_note(messages: list[Message]) -> str | None:
    """The Advisor's most recent note for the initiative (discretion 37b8: most-recent message).
    None if the Advisor hasn't spoken yet."""
    for m in reversed(messages):
        if m.role == "advisor":
            return m.content
    return None


def _unit_review_index(messages: list[Message]) -> dict[str, dict[str, Any]]:
    """Latest Advisor review notes keyed by unit id, read from message metadata. The verify-stage
    review (0009 u5) is posted as an advisor message carrying `review` in metadata; messages are
    oldest-first, so a later review overwrites an earlier one for the same unit."""
    by_unit: dict[str, dict[str, Any]] = {}
    for m in messages:
        review = m.metadata.get("review") if m.metadata else None
        if isinstance(review, dict) and isinstance(review.get("unit_id"), str):
            by_unit[review["unit_id"]] = review
    return by_unit


async def spec_enrichment(store: SpecStore, initiative_id: str) -> dict[str, Any]:
    """The executor-facing enrichment for get_spec (0013 u5 / constraint 9a27): the Advisor's
    latest guidance note, plus per-unit context (the human's verification feedback + the Advisor's
    review notes) so the executor sees the reasoning around a unit, not just the unit. Each field
    is present only when its source data exists."""
    messages = await store.list_messages(initiative_id)
    units = await store.list_units(initiative_id)
    reviews = _unit_review_index(messages)
    unit_context: dict[str, dict[str, Any]] = {}
    for u in units:
        ctx: dict[str, Any] = {}
        if u.submission is not None:
            ctx["submission_summary"] = u.submission.summary
        if u.verdict is not None:
            ctx["verdict"] = u.verdict.verdict
            ctx["verification_feedback"] = u.verdict.feedback
        review = reviews.get(u.id)
        if review is not None:
            ctx["advisor_review"] = {
                "summary": review.get("summary"),
                "concerns": review.get("concerns") or [],
            }
        if ctx:  # only units that actually carry feedback/review
            ctx["title"] = u.title
            ctx["status"] = u.status
            unit_context[u.id] = ctx
    return {
        "advisor_summary": _latest_advisor_note(messages),
        "unit_context": unit_context,
    }


async def summarize_conversation(store: SpecStore, initiative_id: str) -> dict[str, Any]:
    """A compact summary of an initiative's shaping (0013 u5 / constraint 9a27): the key decisions
    with the option chosen, the alternatives rejected, and the human's stated priorities — so an
    executor understands WHY the constraints exist, not just what they are. Deterministic: built
    from the resolved decisions and the human's own turns, no model call (discretion 235d's
    structured-extract option)."""
    if await store.get_initiative(initiative_id) is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    decisions = await store.list_decisions(initiative_id, status="resolved")
    messages = await store.list_messages(initiative_id)
    key_decisions = [
        {"question": d.question, "chosen": d.chosen, "rationale": d.rationale} for d in decisions
    ]
    rejected_alternatives = [
        {"question": d.question, "alternatives": [o for o in d.options if o != d.chosen]}
        for d in decisions
        if any(o != d.chosen for o in d.options)
    ]
    stated_priorities = [m.content for m in messages if m.role == "human"]
    return {
        "initiative_id": initiative_id,
        "key_decisions": key_decisions,
        "rejected_alternatives": rejected_alternatives,
        "stated_priorities": stated_priorities,
    }
