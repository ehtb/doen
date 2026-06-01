"""AI-assisted spec shaping (spec 0006, u2): a plain-language description in, a proposed
structured spec out.

The system prompt distills the spec contract (D1 -> b): the section discipline from the
/spec skill, not the full contract or the MCP operating loop. Relevant priors from memory
are fetched via get_context BEFORE the LLM call (constraint 6) and fed into the prompt, so
the proposal is informed by organizational history. Output is forced into a JSON schema
(constraint 4) and parsed into the existing models — every item born ai_proposed /
proposed (constraint 3) for the human to confirm. A bad call raises LLMError so the caller
leaves the spec untouched (constraint 7)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.llm import LLMError, StructuredLLM, get_shaping_llm
from app.store import AcceptanceCriterion, ContextHit, SpecItem, Verify

SHAPING_SYSTEM_PROMPT = """You are shaping a Doen spec — the living-spec artifact that governs \
how a feature gets built. A good spec lets an executor build the right thing and lets a human \
verify it without reading diffs. From a plain-language feature description (and any relevant \
patterns from past initiatives), draft a complete, well-formed spec. The human will confirm, \
edit, or reject each item — so make it a strong first draft, not the final word.

Fill each section with discipline:
- intent: one short paragraph, plain prose — the problem and the desired outcome, in the human \
voice. Not a task list.
- constraints: hard must / must-not lines the executor will not cross. Each a clear assertion — \
the binding rules and scope fences for THIS feature. Include an architecture invariant only when \
it actually binds this work.
- discretion: explicit latitude — where the executor decides freely (naming, internal structure, \
UI specifics, library choices within constraints). The inverse of constraints.
- constraints + discretion should PARTITION the decision space. If a likely decision falls in \
neither and bears on intent, fold it into one of them rather than leaving it for the agent to \
resolve silently.
- acceptance: how the work is judged. Each criterion must be VERIFIABLE and tagged by kind — \
test, behavior, metric, or human_judgment — with a short detail of how it's checked. Avoid vague \
criteria. Mark the single most important one as the HEADLINE by appending " [HEADLINE]" to its \
text.

Hard rules:
- No estimation anywhere — no story points, hours, or velocity.
- Verifiable acceptance criteria only — if you can't say how it's checked, it doesn't belong.
- Don't invent intent the description doesn't support. Keep it tight: a spec is a contract, not \
an essay.

Return the draft via the proposed_spec tool, matching its schema exactly."""

SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "description": "One short paragraph, plain prose: the problem and the desired outcome.",
        },
        "constraints": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Hard must / must-not lines the executor will not cross.",
        },
        "discretion": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Explicit latitude — where the executor decides freely.",
        },
        "acceptance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "A verifiable criterion. Append ' [HEADLINE]' to the most important one.",
                    },
                    "verify_kind": {
                        "type": "string",
                        "enum": ["test", "behavior", "metric", "human_judgment"],
                    },
                    "verify_detail": {"type": "string", "description": "How it is checked."},
                },
                "required": ["text", "verify_kind", "verify_detail"],
            },
        },
    },
    "required": ["intent", "constraints", "discretion", "acceptance"],
}

_DRAFT = dict(provenance="ai_proposed", status="proposed")


class ShapingResult(BaseModel):
    """The proposed spec components — all ai_proposed/proposed, not yet persisted — plus the
    memory priors that informed them (for transparency / a4)."""

    intent: str
    constraints: list[SpecItem]
    discretion: list[SpecItem]
    acceptance: list[AcceptanceCriterion]
    context_used: list[ContextHit]


def _build_user_message(description: str, hits: list[ContextHit]) -> str:
    parts = [f"Feature description from the human:\n{description.strip()}"]
    if hits:
        priors = "\n".join(
            f"- ({h.type} · {h.initiative_id}, score {h.score}): {h.text}" for h in hits
        )
        parts.append(
            "Relevant patterns from completed initiatives (organizational memory). Reuse what "
            "applies; don't silently contradict a prior decision — if you must diverge, say so in "
            "the relevant item:\n" + priors
        )
    return "\n\n".join(parts)


def _parse(raw: dict[str, Any], hits: list[ContextHit]) -> ShapingResult:
    try:
        constraints = [SpecItem(text=t, **_DRAFT) for t in raw["constraints"]]
        discretion = [SpecItem(text=t, **_DRAFT) for t in raw["discretion"]]
        acceptance = [
            AcceptanceCriterion(
                text=a["text"],
                verify=Verify(kind=a["verify_kind"], detail=a["verify_detail"]),
                **_DRAFT,
            )
            for a in raw["acceptance"]
        ]
    except (KeyError, TypeError, ValueError) as e:
        raise LLMError(f"shaping output did not match the spec schema: {e}") from e
    return ShapingResult(
        intent=str(raw.get("intent", "")).strip(),
        constraints=constraints,
        discretion=discretion,
        acceptance=acceptance,
        context_used=hits,
    )


async def shape_spec(
    store,
    initiative_id: str,
    description: str,
    *,
    llm: StructuredLLM | None = None,
    context_limit: int = 6,
) -> ShapingResult:
    """Draft a proposed spec from a description. get_context runs first (constraint 6 / a4);
    if the corpus is empty it returns nothing and shaping proceeds without priors."""
    llm = llm or get_shaping_llm()
    hits = await store.get_context(description, limit=context_limit)
    raw = await llm.complete_structured(
        system=SHAPING_SYSTEM_PROMPT,
        user=_build_user_message(description, hits),
        schema=SPEC_SCHEMA,
        schema_name="proposed_spec",
    )
    return _parse(raw, hits)
