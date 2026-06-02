"""Discretion Auditor — intercepts raise_decision calls before they reach the human dashboard.

For every escalation an executor raises, the Auditor checks whether the question falls
clearly within one of the spec's confirmed discretion items. If it does — and only with
high confidence — it agent-resolves the decision inline, cites the discretion item, and
returns a suggestion to the calling agent. The human never sees it as an attention item.

When confidence is anything less than high, the decision surfaces to the human as usual.
A false negative (silently handling a real product call) is strictly worse than noise.

BD-13 constraints:
- Runs synchronously inside raise_decision before any attention item is created.
- MUST NOT resolve autonomously — marks as agent-resolved with rationale, not silent drop.
- Agent-resolved decisions remain in the log, distinguished from human-resolved.
- When confidence < high → surface to human (err toward the human).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.models import SpecItem
from app.providers.llm import LLMError, StructuredLLM, get_advisor_llm

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

class AuditResult(BaseModel):
    within_discretion: bool
    discretion_item_id: str | None = None
    discretion_item_text: str | None = None
    suggestion: str | None = None
    reasoning: str = ""


# ---------------------------------------------------------------------------
# LLM schema + prompt
# ---------------------------------------------------------------------------

_AUDITOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "within_discretion": {
            "type": "boolean",
            "description": (
                "True ONLY when this question maps to one of the discretion items with "
                "HIGH confidence — meaning the question is about implementation details or "
                "choices that the discretion item explicitly grants the executor latitude to "
                "decide. False for anything ambiguous, borderline, or not explicitly covered."
            ),
        },
        "discretion_item_id": {
            "type": ["string", "null"],
            "description": "The id of the matching discretion item. Null when within_discretion is false.",
        },
        "reasoning": {
            "type": "string",
            "description": (
                "One short paragraph explaining your confidence assessment. "
                "Be specific about WHY this does or does not match the discretion item."
            ),
        },
        "suggestion": {
            "type": ["string", "null"],
            "description": (
                "When within_discretion is true: a concrete suggestion for the executor "
                "— what to do given the discretion item's latitude. One sentence. "
                "Null when within_discretion is false."
            ),
        },
    },
    "required": ["within_discretion", "reasoning"],
}

_AUDITOR_SYSTEM = """\
You are the Doen Discretion Auditor — an inline gate that decides whether an executor's \
decision question falls clearly within the spec's discretion items.

DISCRETION ITEMS are explicit grants of latitude: the spec author pre-approved these \
decisions and told the executor to decide freely. They partition the decision space from \
constraints (hard must/must-not lines) and from escalations (calls the human must make).

YOUR JOB: Given a decision question and the spec's confirmed discretion items, determine \
whether the question is CLEARLY within one specific discretion item.

CRITICAL BIAS RULE: Only return within_discretion=true when you are HIGH CONFIDENCE. \
When in any doubt — ambiguous scope, partial overlap, vocabulary match but different intent, \
or no single discretion item clearly applies — return within_discretion=false. \
A false negative (silent product call) is strictly worse than surfacing to the human. \
Err toward surfacing.

HIGH CONFIDENCE means:
- The question is specifically about an implementation detail, internal design choice, or \
wording that a discretion item explicitly pre-authorises.
- A reasonable person reading both the question and the discretion item would immediately \
agree: "yes, this is exactly what that discretion item covers."

NOT high confidence:
- The question shares vocabulary with a discretion item but has broader scope.
- The question has product or intent implications beyond the implementation detail.
- The question isn't addressed by any single discretion item clearly.
"""


def _render_discretion_items(items: list[SpecItem]) -> str:
    confirmed = [i for i in items if i.status == "confirmed"]
    if not confirmed:
        return "No confirmed discretion items in this spec."
    lines = ["Confirmed discretion items (id → text):"]
    lines += [f"  {i.id}: {i.text}" for i in confirmed]
    return "\n".join(lines)


def _build_user_message(
    question: str,
    options: list[str],
    recommendation: str | None,
    discretion_items: list[SpecItem],
) -> str:
    parts = [
        f"Decision question: {question}",
        f"Options offered: {', '.join(options)}",
    ]
    if recommendation:
        parts.append(f"Executor's recommendation: {recommendation}")
    parts.append("")
    parts.append(_render_discretion_items(discretion_items))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def audit_decision(
    question: str,
    options: list[str],
    recommendation: str | None,
    discretion_items: list[SpecItem],
    *,
    llm: StructuredLLM | None = None,
) -> AuditResult:
    """Check whether this decision question is clearly within the spec's discretion.

    Returns AuditResult with within_discretion=True only when high-confidence. On any
    LLMError, returns a safe fallback (within_discretion=False) so the decision always
    surfaces to the human — judge outages must never silently suppress escalations."""
    confirmed_items = [i for i in discretion_items if i.status == "confirmed"]
    if not confirmed_items:
        return AuditResult(
            within_discretion=False,
            reasoning="No confirmed discretion items — no gate to check against.",
        )

    llm = llm or get_advisor_llm()
    try:
        raw = await llm.complete_structured(
            system=_AUDITOR_SYSTEM,
            user=_build_user_message(question, options, recommendation, confirmed_items),
            schema=_AUDITOR_SCHEMA,
            schema_name="discretion_audit",
        )
    except LLMError:
        return AuditResult(
            within_discretion=False,
            reasoning="Auditor LLM unavailable — decision surfaced to human as a safe fallback.",
        )

    within = bool(raw.get("within_discretion", False))
    item_id = raw.get("discretion_item_id") if within else None

    # Look up the matched item text for the agent-facing response.
    item_text: str | None = None
    if item_id:
        matched = next((i for i in confirmed_items if i.id == item_id), None)
        if matched:
            item_text = matched.text
        else:
            # LLM hallucinated an item id — treat as not within discretion.
            within = False
            item_id = None

    return AuditResult(
        within_discretion=within,
        discretion_item_id=item_id,
        discretion_item_text=item_text,
        suggestion=raw.get("suggestion") if within else None,
        reasoning=str(raw.get("reasoning", "")),
    )
