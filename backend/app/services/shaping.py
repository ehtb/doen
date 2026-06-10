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

from app.config import MAX_INJECTED_MEMORY_CRITERIA, MEMORY_VERIFICATION_THRESHOLD
from app.exceptions import NotFoundError, ValidationError
from app.models import (
    AcceptanceCriterion,
    AdvisorClassification,
    ContextHit,
    Initiative,
    InitiativeType,
    Spec,
    SpecItem,
    Verify,
)
from app.providers.llm import LLMError, StructuredLLM, get_review_llm, get_shaping_llm
from app.store import SpecStore

from pathlib import Path

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
SHAPING_SYSTEM_PROMPT = (_PROMPTS / "shaping.txt").read_text().strip()
SHAPING_SYSTEM_PROMPT_RESEARCH = (_PROMPTS / "shaping-research.txt").read_text().strip()
TYPE_INFERENCE_SYSTEM_PROMPT = (_PROMPTS / "type-inference.txt").read_text().strip()

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
                    "verify": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["test", "behavior", "metric", "human_judgment"],
                            },
                            "detail": {"type": "string", "description": "How it is checked."},
                        },
                        "required": ["kind", "detail"],
                    },
                },
                "required": ["text", "verify"],
            },
        },
    },
    "required": ["title", "intent", "constraints", "discretion", "acceptance"],
}


# --- BD-14: Advisor self-review classification pass ----------------------------------

CLASSIFICATION_SYSTEM_PROMPT = (_PROMPTS / "classification.txt").read_text().strip()

CLASSIFICATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["confident", "flagged", "uncertain"],
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "One sentence, ≤ 15 words. No internal item IDs. "
                            "Confident: short phrase. "
                            "Flagged: the specific concern; cite initiative ID if relevant. "
                            "Uncertain: a direct question ending in '?'."
                        ),
                    },
                },
                "required": ["item_id", "category", "reason"],
            },
        }
    },
    "required": ["classifications"],
}


def _build_classification_user_message(
    proposed: list[tuple[str, SpecItem]],
    high_score_hits: list[ContextHit],
    superseded_hits: list[ContextHit] | None = None,
) -> str:
    parts: list[str] = []
    if high_score_hits:
        priors = "\n".join(
            # BD-17: include heuristic_id so the LLM can cite it in confident reasons.
            f"  - [{h.initiative_id}] ({h.type}, score {h.score:.2f}"
            + (f", id={h.heuristic_id}" if h.heuristic_id else "")
            + f"): {h.text}"
            for h in high_score_hits
        )
        parts.append(
            "HIGH-RELEVANCE PRIORS (score ≥ 0.75) — any item that contradicts one of "
            "these MUST be classified as 'flagged'. For confident items, cite the source id:\n"
            + priors
        )
    # BD-17: superseded heuristics — items grounded in these must be flagged (item_9311fd139032).
    if superseded_hits:
        sup_lines = "\n".join(
            f"  - [{h.initiative_id}] superseded_by={h.superseded_by}: {h.text}"
            for h in superseded_hits
        )
        parts.append(
            "SUPERSEDED HEURISTICS — any item that would have been grounded in one of these "
            "MUST be classified as 'flagged' with reason citing the supersession:\n" + sup_lines
        )
    item_lines: list[str] = []
    for section, item in proposed:
        if isinstance(item, AcceptanceCriterion):
            item_lines.append(
                f"  item_id={item.id}  section={section}\n"
                f"    text: {item.text}\n"
                f"    verify: [{item.verify.kind}] {item.verify.detail}"
            )
        else:
            item_lines.append(
                f"  item_id={item.id}  section={section}\n"
                f"    text: {item.text}"
            )
    parts.append("Items to classify:\n" + "\n".join(item_lines))
    return "\n\n".join(parts)


def _build_shaping_synthesis(
    confident: list[SpecItem],
    flagged: list[tuple[SpecItem, str]],
    uncertain: list[tuple[SpecItem, str]],
) -> str:
    lines: list[str] = []
    n = len(confident)
    if n:
        noun = "item" if n == 1 else "items"
        pronoun = "it" if n == 1 else "them"
        lines.append(f"{n} {noun} look solid — approve {pronoun} as a batch?")
    if flagged:
        m = len(flagged)
        lines.append(f"\n{m} flagged:")
        for item, reason in flagged:
            snippet = item.text[:80].rstrip() + ("…" if len(item.text) > 80 else "")
            lines.append(f"  • \"{snippet}\" — {reason}")
    if uncertain:
        k = len(uncertain)
        verb = "needs" if k == 1 else "need"
        lines.append(f"\n{k} {verb} your call:")
        for item, reason in uncertain:
            snippet = item.text[:80].rstrip() + ("…" if len(item.text) > 80 else "")
            lines.append(f"  • \"{snippet}\" — {reason}")
    return "\n".join(lines)


async def _classify_and_annotate(
    spec: Spec,
    context_used: list[ContextHit],
    *,
    superseded_hits: list[ContextHit] | None = None,
    llm: StructuredLLM | None = None,
) -> None:
    """BD-14/BD-17: run the Advisor's self-review classification pass on all proposed items.

    Mutates each proposed item's advisor_classification / advisor_classification_reason
    in-place and sets spec.shaping_review_synthesis. Failures are non-fatal — items are
    saved without classification data rather than blocking shaping.

    BD-17: `superseded_hits` are heuristics that have been superseded. Items that would have
    been classified as 'confident' based on superseded heuristics are downgraded to 'flagged'
    (constraint item_9311fd139032 / item_226144412674)."""
    proposed: list[tuple[str, SpecItem]] = []
    for section in ("constraints", "discretion", "acceptance"):
        for item in getattr(spec, section):
            if item.status == "proposed":
                proposed.append((section, item))
    if not proposed:
        return

    llm = llm or get_review_llm()
    high_score_hits = [h for h in context_used if h.score >= MEMORY_VERIFICATION_THRESHOLD]
    # BD-17: superseded heuristics that match at high relevance — must not ground confident items.
    high_superseded = [h for h in (superseded_hits or []) if h.score >= MEMORY_VERIFICATION_THRESHOLD]

    try:
        raw = await llm.complete_structured(
            system=CLASSIFICATION_SYSTEM_PROMPT,
            user=_build_classification_user_message(proposed, high_score_hits, high_superseded),
            schema=CLASSIFICATION_SCHEMA,
            schema_name="classify_items",
        )
    except Exception:
        return  # degraded but not broken — items saved without classification

    cls_map: dict[str, dict] = {
        c["item_id"]: c for c in raw.get("classifications", [])
    }

    # BD-17: build a set of superseded heuristic IDs so we can enforce the constraint
    # post-classification — the LLM might still output 'confident' for those.
    superseded_heuristic_ids: set[str] = {
        h.heuristic_id for h in (superseded_hits or []) if h.heuristic_id
    }

    confident: list[SpecItem] = []
    flagged: list[tuple[SpecItem, str]] = []
    uncertain: list[tuple[SpecItem, str]] = []

    for _section, item in proposed:
        cls = cls_map.get(item.id)
        if cls is None:
            # LLM omitted this item — default to uncertain
            item.advisor_classification = "uncertain"
            item.advisor_classification_reason = "Not classified — treat as uncertain"
            uncertain.append((item, item.advisor_classification_reason))
            continue
        category: AdvisorClassification = cls.get("category", "uncertain")
        reason: str = cls.get("reason", "")

        # BD-17 hard constraint: if the reason cites a superseded heuristic ID, downgrade.
        if category == "confident" and superseded_heuristic_ids:
            if any(hid in reason for hid in superseded_heuristic_ids):
                category = "flagged"
                reason = f"Grounding heuristic superseded; {reason}"

        item.advisor_classification = category
        item.advisor_classification_reason = reason
        if category == "confident":
            confident.append(item)
        elif category == "flagged":
            flagged.append((item, reason))
        else:
            uncertain.append((item, reason))

    spec.shaping_review_synthesis = _build_shaping_synthesis(confident, flagged, uncertain)


class ProposedUnit(BaseModel):
    """One proposed work unit from shaping (0011 C2): a title, a scope, and the indexes of the
    acceptance criteria it satisfies. Indexes reference positions in ShapingResult.acceptance."""

    title: str
    scope: str = ""
    criterion_indexes: list[int] = []


class ShapingResult(BaseModel):
    """The proposed spec components — all ai_proposed/proposed, not yet persisted — plus the
    memory priors that informed them (for transparency / a4)."""

    title: str = ""
    intent: str
    constraints: list[SpecItem]
    discretion: list[SpecItem]
    acceptance: list[AcceptanceCriterion]
    units: list[ProposedUnit] = []
    context_used: list[ContextHit]


def _memory_verification_criterion(hit: ContextHit) -> AcceptanceCriterion:
    """BD-12: synthesize a Memory Verification acceptance criterion for a high-scoring memory
    hit. Indistinguishable in structure from LLM-generated criteria so it flows through the
    same confirm / submit_evidence / human-verdict lifecycle."""
    snippet = hit.text[:120].rstrip()
    if len(hit.text) > 120:
        snippet += "…"
    return AcceptanceCriterion(
        text=(
            f"Verify that memory entry [{hit.initiative_id}] (\"{snippet}\") still accurately "
            "reflects the current codebase. If drift is found, call report_memory_drift with "
            f"memory_id=\"{hit.initiative_id}\" and your findings; if it remains accurate, "
            "document that as evidence."
        ),
        verify=Verify(
            kind="behavior",
            detail=(
                f"Inspect the live codebase against the claim in memory entry {hit.initiative_id}. "
                "Submit evidence of either accuracy (no action needed) or discrepancy "
                "(report_memory_drift filed). Human approves once evidence is submitted."
            ),
        ),
        provenance="ai_proposed",
        status="proposed",
    )


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
                verify=Verify(**a["verify"]),
                provenance="ai_proposed",
                status="proposed",
            )
            for a in raw["acceptance"]
        ]
        units = [
            ProposedUnit(
                title=u["title"],
                scope=u.get("scope", ""),
                criterion_indexes=u.get("criteria", []),
            )
            for u in raw.get("units", [])
        ]
    except (KeyError, TypeError, ValueError) as e:
        raise LLMError(f"shaping output did not match the spec schema: {e}") from e

    # BD-12: inject Memory Verification criteria for high-scoring memory hits. Capped at
    # MAX_INJECTED_MEMORY_CRITERIA (default 2) to prevent criteria fatigue when many hits
    # score above the threshold. Deduped by initiative_id; hits already sorted by score.
    seen_initiatives: set[str] = set()
    for hit in hits:
        if len(seen_initiatives) >= MAX_INJECTED_MEMORY_CRITERIA:
            break
        if (
            hit.type == "memory"
            and hit.score >= MEMORY_VERIFICATION_THRESHOLD
            and hit.initiative_id not in seen_initiatives
        ):
            acceptance.append(_memory_verification_criterion(hit))
            seen_initiatives.add(hit.initiative_id)

    return ShapingResult(
        title=str(raw.get("title", "")).strip(),
        intent=str(raw.get("intent", "")).strip(),
        constraints=constraints,
        discretion=discretion,
        acceptance=acceptance,
        units=units,
        context_used=hits,
    )


async def shape_spec(
    store,
    description: str,
    *,
    project_id: str | None = None,
    initiative_type: InitiativeType = "engineering",
    llm: StructuredLLM | None = None,
    context_limit: int = 6,
) -> ShapingResult:
    """Draft a proposed spec from a description. get_context runs first (constraint 6 / a4);
    when the initiative belongs to a project the search is project-scoped (0010 constraint 4),
    so sibling patterns surface first. An empty corpus returns nothing and shaping proceeds
    without priors. BD-15: `initiative_type` selects the research vs. engineering framing.
    Only active (non-superseded) heuristics surface as priors — constraint item_74a52b7067a3."""
    llm = llm or get_shaping_llm()
    system_prompt = (
        SHAPING_SYSTEM_PROMPT_RESEARCH if initiative_type == "research" else SHAPING_SYSTEM_PROMPT
    )
    hits = await store.get_context(description, limit=context_limit, project_id=project_id)
    raw = await llm.complete_structured(
        system=system_prompt,
        user=_build_user_message(description, hits),
        schema=SPEC_SCHEMA,
        schema_name="proposed_spec",
    )
    return _parse(raw, hits)


async def shape_and_persist(
    store: SpecStore,
    initiative_id: str,
    description: str,
    *,
    classification_llm: StructuredLLM | None = None,
) -> Spec:
    """Shape a spec from a description, then persist the proposal: refresh the proposed
    items (keeping confirmed ones), and set intent only when it's still blank. A failed LLM
    call raises LLMError before the save, so the spec is left untouched (constraint 7).

    BD-14: runs the Advisor's self-review classification pass automatically after shaping.
    BD-17: also fetches superseded heuristics so the classifier can flag items that would
    have been grounded in stale heuristics (constraint item_9311fd139032)."""
    if not description.strip():
        raise ValidationError("a description is required to shape a spec")
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {initiative_id}")
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    result = await shape_spec(
        store, description, project_id=init.project_id, initiative_type=init.initiative_type
    )
    spec.constraints = [i for i in spec.constraints if i.status != "proposed"] + result.constraints
    spec.discretion = [i for i in spec.discretion if i.status != "proposed"] + result.discretion
    spec.acceptance = [i for i in spec.acceptance if i.status != "proposed"] + result.acceptance
    if not spec.intent.strip() and result.intent:
        spec.intent = result.intent
    # BD-17: fetch superseded heuristics to inform the classifier.
    all_hits = await store.get_context(
        description, limit=8, project_id=init.project_id,
        include_superseded_heuristics=True,
    )
    superseded_hits = [h for h in all_hits if h.type == "heuristic" and h.superseded_by]
    # BD-14: classify proposed items; non-fatal if the LLM call fails.
    await _classify_and_annotate(
        spec, result.context_used, superseded_hits=superseded_hits, llm=classification_llm,
    )
    return await store.save_spec(spec)


def _fallback_title(description: str) -> str:
    """A title when the model didn't return one — the first few words of the description, so the
    initiative is still named (and gets a sensible slug)."""
    words = description.split()
    return " ".join(words[:8]) or "Untitled initiative"


async def create_initiative_bare(
    store: SpecStore,
    project_id: str,
    description: str,
    *,
    initiative_type: InitiativeType = "engineering",
) -> Initiative:
    """Fast path: validate, create the initiative row under a provisional title, mark the spec
    as shaping_status='pending', and return immediately. The LLM work runs as a background task
    via fill_spec_from_description so the caller can redirect the user right away."""
    if not description.strip():
        raise ValidationError("a description is required to start an initiative")
    if await store.get_project(project_id) is None:
        raise NotFoundError(f"no project {project_id}")
    title = _fallback_title(description)
    init = await store.create_initiative(title, project_id, initiative_type=initiative_type)
    spec = await store.get_spec(init.id)
    assert spec is not None
    spec.shaping_status = "pending"
    spec.original_description = description
    await store.save_spec(spec)
    return init


async def fill_spec_from_description(
    store: SpecStore,
    initiative_id: str,
    description: str,
    *,
    project_id: str,
    initiative_type: InitiativeType = "engineering",
    llm: StructuredLLM | None = None,
    classification_llm: StructuredLLM | None = None,
) -> None:
    """Background task: shape the spec via the LLM, populate all sections, and mark
    shaping_status='complete'. On any failure, marks shaping_status='error' so the UI
    can surface a degraded state instead of an infinite spinner."""
    try:
        result = await shape_spec(
            store, description, project_id=project_id, initiative_type=initiative_type, llm=llm
        )
        title = result.title.strip() or _fallback_title(description)
        spec = await store.get_spec(initiative_id)
        if spec is None:
            return
        spec.title = title
        spec.intent = result.intent
        spec.constraints = result.constraints
        spec.discretion = result.discretion
        spec.acceptance = result.acceptance
        spec.shaping_status = "complete"
        all_hits = await store.get_context(
            description, limit=8, project_id=project_id,
            include_superseded_heuristics=True,
        )
        superseded_hits = [h for h in all_hits if h.type == "heuristic" and h.superseded_by]
        await _classify_and_annotate(
            spec, result.context_used, superseded_hits=superseded_hits, llm=classification_llm,
        )
        await store.save_spec(spec)
        await store.update_initiative_title(initiative_id, title)
    except Exception:
        try:
            spec = await store.get_spec(initiative_id)
            if spec is not None:
                spec.shaping_status = "error"
                await store.save_spec(spec)
        except Exception:
            pass


async def create_from_description(
    store: SpecStore,
    project_id: str,
    description: str,
    *,
    initiative_type: InitiativeType = "engineering",
    llm: StructuredLLM | None = None,
    classification_llm: StructuredLLM | None = None,
) -> Initiative:
    """Creation IS shaping (0011 C2): from a free-text description, the Advisor drafts the whole
    spec — title, intent, constraints, discretion, acceptance — all ai_proposed for the human to
    confirm item by item. Shapes first (a failed LLM call -> 502 leaves nothing created), then
    scaffolds the initiative under its generated title and persists the proposed items.
    Every initiative belongs to a project (no orphan specs) — an unknown project_id -> 404.

    BD-14: runs the Advisor's self-review classification pass automatically after shaping.
    BD-15: `initiative_type` persists the user-selected type (defaults to engineering)."""
    if not description.strip():
        raise ValidationError("a description is required to start an initiative")
    if await store.get_project(project_id) is None:
        raise NotFoundError(f"no project {project_id}")

    result = await shape_spec(
        store, description, project_id=project_id, initiative_type=initiative_type, llm=llm
    )
    title = result.title.strip() or _fallback_title(description)

    init = await store.create_initiative(title, project_id, initiative_type=initiative_type)
    spec = await store.get_spec(init.id)
    assert spec is not None  # just scaffolded by create_initiative
    spec.intent = result.intent
    spec.constraints = result.constraints
    spec.discretion = result.discretion
    spec.acceptance = result.acceptance
    # BD-17: fetch superseded heuristics for the classifier.
    all_hits = await store.get_context(
        description, limit=8, project_id=project_id,
        include_superseded_heuristics=True,
    )
    superseded_hits = [h for h in all_hits if h.type == "heuristic" and h.superseded_by]
    # BD-14: classify proposed items; non-fatal if the LLM call fails.
    await _classify_and_annotate(
        spec, result.context_used, superseded_hits=superseded_hits, llm=classification_llm,
    )
    await store.save_spec(spec)
    return init


# --- BD-28: initiative type inference for create_spec MCP tool -----------------------

_TYPE_INFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "initiative_type": {
            "type": "string",
            "enum": ["engineering", "research"],
        }
    },
    "required": ["initiative_type"],
}


async def infer_initiative_type(
    description: str,
    llm: StructuredLLM | None = None,
) -> InitiativeType:
    """Classify a description as 'engineering' (building/changing software) or 'research'
    (investigating/evaluating options). Falls back to 'engineering' on any LLM failure."""
    llm = llm or get_shaping_llm()
    try:
        result = await llm.complete_structured(
            system=TYPE_INFERENCE_SYSTEM_PROMPT,
            user=description,
            schema=_TYPE_INFERENCE_SCHEMA,
            schema_name="initiative_type_classification",
        )
        t = result.get("initiative_type", "engineering")
        return "research" if t == "research" else "engineering"
    except LLMError:
        return "engineering"
