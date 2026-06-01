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

from app.exceptions import NotFoundError, ValidationError
from app.models import (
    AcceptanceCriterion,
    ContextHit,
    Initiative,
    Spec,
    SpecItem,
    Verify,
)
from app.providers.llm import LLMError, StructuredLLM, get_shaping_llm
from app.store import SpecStore

SHAPING_SYSTEM_PROMPT = """You are shaping a Doen spec — the living-spec artifact that governs \
how a feature gets built. A good spec lets an executor build the right thing and lets a human \
verify it without reading diffs. From a plain-language description (and any relevant patterns \
from past initiatives), draft a complete, well-formed spec. The human will confirm, edit, or \
reject each item — so make it a strong first draft, not the final word.

Fill each section with discipline:
- title: a short, imperative name for the initiative — a few words, drawn from the description.
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
Size the spec to the work — infer the scale from the description, never ask and never use a size \
label. A small bug fix or tweak ("fix the misaligned login button") gets a LIGHTWEIGHT spec: \
about one constraint, one acceptance criterion, and one unit. A substantial feature gets the FULL \
structure: several constraints, multiple criteria, and a handful of units. Don't pad a small \
change into a heavy spec, and don't compress a large one — match the structure to the real size.

Hard rules:
- No estimation anywhere — no story points, hours, or velocity.
- Verifiable acceptance criteria only — if you can't say how it's checked, it doesn't belong.
- Don't invent intent the description doesn't support. Keep it tight: a spec is a contract, not \
an essay.

Return the draft via the proposed_spec tool, matching its schema exactly."""

SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "A short imperative name for the initiative — a few words.",
        },
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
    "required": ["title", "intent", "constraints", "discretion", "acceptance"],
}


class ShapingResult(BaseModel):
    """The proposed spec components — all ai_proposed/proposed, not yet persisted — plus the
    memory priors that informed them (for transparency / a4)."""

    title: str = ""
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
        constraints = [
            SpecItem(text=t, provenance="ai_proposed", status="proposed")
            for t in raw["constraints"]
        ]
        discretion = [
            SpecItem(text=t, provenance="ai_proposed", status="proposed")
            for t in raw["discretion"]
        ]
        acceptance = [
            AcceptanceCriterion(
                text=a["text"],
                verify=Verify(kind=a["verify_kind"], detail=a["verify_detail"]),
                provenance="ai_proposed",
                status="proposed",
            )
            for a in raw["acceptance"]
        ]
    except (KeyError, TypeError, ValueError) as e:
        raise LLMError(f"shaping output did not match the spec schema: {e}") from e
    return ShapingResult(
        title=str(raw.get("title", "")).strip(),
        intent=str(raw.get("intent", "")).strip(),
        constraints=constraints,
        discretion=discretion,
        acceptance=acceptance,
        context_used=hits,
    )


async def shape_spec(
    store,
    description: str,
    *,
    project_id: str | None = None,
    llm: StructuredLLM | None = None,
    context_limit: int = 6,
) -> ShapingResult:
    """Draft a proposed spec from a description. get_context runs first (constraint 6 / a4);
    when the initiative belongs to a project the search is project-scoped (0010 constraint 4),
    so sibling patterns surface first. An empty corpus returns nothing and shaping proceeds
    without priors."""
    llm = llm or get_shaping_llm()
    hits = await store.get_context(description, limit=context_limit, project_id=project_id)
    raw = await llm.complete_structured(
        system=SHAPING_SYSTEM_PROMPT,
        user=_build_user_message(description, hits),
        schema=SPEC_SCHEMA,
        schema_name="proposed_spec",
    )
    return _parse(raw, hits)


async def shape_and_persist(store: SpecStore, initiative_id: str, description: str) -> Spec:
    """Shape a spec from a description, then persist the proposal: refresh the proposed
    items (keeping confirmed ones), and set intent only when it's still blank. A failed LLM
    call raises LLMError before the save, so the spec is left untouched (constraint 7)."""
    if not description.strip():
        raise ValidationError("a description is required to shape a spec")
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {initiative_id}")
    init = await store.get_initiative(initiative_id)
    project_id = init.project_id if init else None
    result = await shape_spec(store, description, project_id=project_id)
    spec.constraints = [i for i in spec.constraints if i.status != "proposed"] + result.constraints
    spec.discretion = [i for i in spec.discretion if i.status != "proposed"] + result.discretion
    spec.acceptance = [i for i in spec.acceptance if i.status != "proposed"] + result.acceptance
    if not spec.intent.strip() and result.intent:
        spec.intent = result.intent
    return await store.save_spec(spec)


def _fallback_title(description: str) -> str:
    """A title when the model didn't return one — the first few words of the description, so the
    initiative is still named (and gets a sensible slug)."""
    words = description.split()
    return " ".join(words[:8]) or "Untitled initiative"


async def create_from_description(
    store: SpecStore,
    project_id: str,
    description: str,
    *,
    llm: StructuredLLM | None = None,
) -> Initiative:
    """Creation IS shaping (0011 C2): from a free-text description, the Advisor drafts the whole
    spec — title, intent, constraints, discretion, acceptance, and proposed units — all
    ai_proposed for the human to confirm item by item. Shapes first (a failed LLM call -> 502
    leaves nothing created), then scaffolds the initiative under its generated title, persists the
    proposed items, and proposes the units. Every initiative belongs to a project (no orphan
    specs) — an unknown project_id -> 404."""
    if not description.strip():
        raise ValidationError("a description is required to start an initiative")
    if await store.get_project(project_id) is None:
        raise NotFoundError(f"no project {project_id}")

    result = await shape_spec(store, description, project_id=project_id, llm=llm)
    title = result.title.strip() or _fallback_title(description)

    init = await store.create_initiative(title, project_id)
    spec = await store.get_spec(init.id)
    assert spec is not None  # just scaffolded by create_initiative
    spec.intent = result.intent
    spec.constraints = result.constraints
    spec.discretion = result.discretion
    spec.acceptance = result.acceptance
    await store.save_spec(spec)
    return init
