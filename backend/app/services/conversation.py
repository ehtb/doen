"""Conversation service (spec 0009 u1; spec uvama): assemble the Advisor's context.

It does NOT call the LLM and does NOT store messages — conversations are browser-local now
(spec uvama), so the windowed history arrives in the Advisor request and is passed in here. This
assembles the explicit, bounded context an Advisor call reads (constraint 1): the recent-message
window + the current spec + relevant memory. Keeping the assembly here, framework-agnostic and
LLM-free, makes it testable on its own and reusable from both the rail endpoint and the MCP
briefing (u4).
"""

from __future__ import annotations

from typing import Any

from app.exceptions import NotFoundError
from app.models import ConversationContext, Message, Spec
from app.store import SpecStore


async def assemble_context(
    store: SpecStore,
    initiative_id: str,
    *,
    messages: list[Message],
    memory_limit: int = 5,
) -> ConversationContext:
    """Build the bounded context for an Advisor turn (constraint 1) from the windowed `messages`
    the browser sent (already including the new human turn). Memory is retrieved off the most
    recent human turn (falling back to the spec's intent/title) so the hits are relevant to where
    the conversation is, not the initiative as a whole."""
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    spec = await store.get_spec(initiative_id)
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


# --- BD-5: enrich the executor's view of a spec ------------------------------------
async def spec_enrichment(store: SpecStore, initiative_id: str) -> dict[str, Any]:
    """The executor-facing enrichment for get_spec. BD-5 removes unit_context; criteria
    verification state is surfaced directly on the spec's acceptance criteria fields."""
    return {"advisor_summary": None, "unit_context": {}}


async def summarize_conversation(store: SpecStore, initiative_id: str) -> dict[str, Any]:
    """A compact summary of an initiative's shaping (0013 u5 / constraint 9a27): the key decisions
    with the option chosen and the alternatives rejected — so an executor understands WHY the
    constraints exist, not just what they are. Deterministic: built from the resolved decisions, no
    model call.

    `stated_priorities` used to carry the human's own conversation turns, but conversations are
    browser-local now (spec uvama, decision dec_0397d7a8f45e/A) — the backend can't read them — so
    it degrades to an empty list. The durable reasoning (resolved decisions) is unaffected."""
    if await store.get_initiative(initiative_id) is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    decisions = await store.list_decisions(initiative_id, status="resolved")
    key_decisions = [
        {"question": d.question, "chosen": d.chosen, "rationale": d.rationale} for d in decisions
    ]
    rejected_alternatives = [
        {"question": d.question, "alternatives": [o for o in d.options if o != d.chosen]}
        for d in decisions
        if any(o != d.chosen for o in d.options)
    ]
    return {
        "initiative_id": initiative_id,
        "key_decisions": key_decisions,
        "rejected_alternatives": rejected_alternatives,
        "stated_priorities": [],
    }
