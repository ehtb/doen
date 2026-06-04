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
about one constraint and one acceptance criterion. A substantial feature gets the FULL structure: \
several constraints, multiple criteria. Don't pad a small change into a heavy spec, and don't \
compress a large one — match the structure to the real size.

Hard rules:
- No estimation anywhere — no story points, hours, or velocity.
- Verifiable acceptance criteria only — if you can't say how it's checked, it doesn't belong.
- Don't invent intent the description doesn't support. Keep it tight: a spec is a contract, not \
an essay.

Return the draft via the proposed_spec tool, matching its schema exactly."""

SHAPING_SYSTEM_PROMPT_RESEARCH = """You are shaping a Doen spec for a RESEARCH initiative — \
one where the goal is to reach a well-reasoned conclusion, not ship code. The spec contract is \
the same (intent, constraints, discretion, acceptance), but the framing shifts:
- intent: state the question being investigated and the desired level of certainty or insight.
- constraints: the scope fences and methodological must-nots (e.g. "must cover providers X, Y, Z", \
"must not include providers with no API"). Each a hard boundary on the investigation.
- discretion: where the investigator decides freely (depth of analysis, which secondary sources, \
presentation format).
- acceptance: how a satisfactory answer is recognised. Criteria should be verifiable findings \
or conclusions, not shipped code. Use human_judgment or behavior kinds. Avoid test/metric unless \
the investigation genuinely produces a measurable output. Mark the most important criterion \
HEADLINE.

Hard rules:
- No estimation anywhere — no story points, hours, or velocity.
- Verifiable acceptance criteria only — if you can't say how it's checked, it doesn't belong.
- Don't invent intent the description doesn't support.

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

CLASSIFICATION_SYSTEM_PROMPT = """You are the Doen Advisor performing a self-review \
classification pass on newly proposed spec items.

Classify each item into exactly one category:
- **confident**: Clear, well-formed, and consistent with prior organisational memory. \
No obvious concerns — safe to batch-approve.
- **flagged**: Has a specific, nameable concern — conflicts with a prior initiative's \
decision, vague wording that creates executor ambiguity, or an acceptance criterion that \
cannot be practically verified. Name the exact concern.
- **uncertain**: A genuine judgment call where you cannot determine the right answer from \
the context provided — a design or intent decision that needs the human's input. Explain \
what the judgment is.

HARD RULE: If an item's text contradicts or conflicts with any "HIGH-RELEVANCE PRIOR" \
listed below (score ≥ 0.75), you MUST classify it as "flagged", not "confident" or \
"uncertain". Cite the memory entry by its initiative_id.

Acceptance criteria notes:
- A "test" criterion must describe a concrete automated check; if it doesn't → flag it.
- "human_judgment" criteria are inherently verifiable — fine as-is.

Return every item. Provide a reason for every item — brief for confident ("looks good"), \
specific for flagged or uncertain."""

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
                            "Brief for confident. Specific concern for flagged — "
                            "cite the memory initiative_id when it conflicts with a prior. "
                            "The judgment question for uncertain."
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
) -> str:
    parts: list[str] = []
    if high_score_hits:
        priors = "\n".join(
            f"  - [{h.initiative_id}] ({h.type}, score {h.score:.2f}): {h.text}"
            for h in high_score_hits
        )
        parts.append(
            "HIGH-RELEVANCE PRIORS (score ≥ 0.75) — any item that contradicts one of "
            "these MUST be classified as 'flagged':\n" + priors
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
    llm: StructuredLLM | None = None,
) -> None:
    """BD-14: run the Advisor's self-review classification pass on all proposed items.

    Mutates each proposed item's advisor_classification / advisor_classification_reason
    in-place and sets spec.shaping_review_synthesis. Failures are non-fatal — items are
    saved without classification data rather than blocking shaping."""
    proposed: list[tuple[str, SpecItem]] = []
    for section in ("constraints", "discretion", "acceptance"):
        for item in getattr(spec, section):
            if item.status == "proposed":
                proposed.append((section, item))
    if not proposed:
        return

    llm = llm or get_review_llm()
    high_score_hits = [h for h in context_used if h.score >= MEMORY_VERIFICATION_THRESHOLD]

    try:
        raw = await llm.complete_structured(
            system=CLASSIFICATION_SYSTEM_PROMPT,
            user=_build_classification_user_message(proposed, high_score_hits),
            schema=CLASSIFICATION_SCHEMA,
            schema_name="classify_items",
        )
    except Exception:
        return  # degraded but not broken — items saved without classification

    cls_map: dict[str, dict] = {
        c["item_id"]: c for c in raw.get("classifications", [])
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
    without priors. BD-15: `initiative_type` selects the research vs. engineering framing."""
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
    Classification failure is non-fatal — items are saved without classification data."""
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
    # BD-14: classify proposed items; non-fatal if the LLM call fails
    await _classify_and_annotate(spec, result.context_used, llm=classification_llm)
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
    # BD-14: classify proposed items; non-fatal if the LLM call fails
    await _classify_and_annotate(spec, result.context_used, llm=classification_llm)
    await store.save_spec(spec)
    return init
