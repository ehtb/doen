"""The Doen Advisor: a state-aware thinking partner on the conversation rail.

The prompt is the product. The Advisor is grounded, every turn, in four things: the
spec-contract discipline (distilled), the current spec (with criteria verification status),
relevant organisational memory, and the recent conversation. Its mode shifts with the
initiative's four-stage lifecycle (BD-5: draft / building / learning / complete).

It reuses the 0006 LLM provider and forces a structured turn — a `reply` plus optional
`proposals` the frontend renders as cards. Proposals are never written to the spec here.

D2 -> c: "shape this initiative: <description>" is a rail command — it reuses the 0006
one-shot full-draft generation, surfacing the whole draft as proposal cards.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.exceptions import NotFoundError, ValidationError
from app.models import (
    AcceptanceCriterion,
    ContextHit,
    ConversationContext,
    InitiativeType,
    Message,
    ProjectContext,
    Spec,
    SpecItem,
    Verify,
    short_id,
)
from app.providers.llm import LLMError, StructuredLLM, get_advisor_llm
from app.schemas import ProjectSynthesisResponse, Proposal, WhatWeKnow
from app.services.conversation import assemble_context
from app.services.shaping import ShapingResult, shape_spec
from app.store import MESSAGE_WINDOW, SpecStore

# --- the prompt -----------------------------------------------------------------------
_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
ADVISOR_BASE_PROMPT = (_PROMPTS / "advisor-base.txt").read_text().strip()
ADVISOR_OUTPUT_CONTRACT = (_PROMPTS / "advisor-output-contract.txt").read_text().strip()

# BD-5: four-stage lifecycle. The Advisor's mode shifts with the state.
STATE_GUIDANCE: dict[str, str] = {
    "draft": (_PROMPTS / "advisor-state-draft.txt").read_text().strip(),
    "building": (_PROMPTS / "advisor-state-building.txt").read_text().strip(),
    "learning": (_PROMPTS / "advisor-state-learning.txt").read_text().strip(),
    "complete": (_PROMPTS / "advisor-state-complete.txt").read_text().strip(),
}

# BD-15: research-specific mode guidance — investigation framing, no executor/MCP references.
STATE_GUIDANCE_RESEARCH: dict[str, str] = {
    "draft": (_PROMPTS / "advisor-state-research-draft.txt").read_text().strip(),
    "building": (_PROMPTS / "advisor-state-research-building.txt").read_text().strip(),
    "learning": (_PROMPTS / "advisor-state-research-learning.txt").read_text().strip(),
    "complete": (_PROMPTS / "advisor-state-research-complete.txt").read_text().strip(),
}

# BD-15: Advisor identity prefix adapted per initiative type.
RESEARCH_TYPE_NOTE = (_PROMPTS / "advisor-research-type-note.txt").read_text().strip()

PROJECT_COHERENCE_PROMPT = (_PROMPTS / "advisor-project-coherence.txt").read_text().strip()

ADVISOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "The Advisor's message, shown in the rail."},
        "proposals": {
            "type": "array",
            "description": "Spec items proposed for the human to confirm. Empty unless proposing.",
            "items": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["constraints", "discretion", "acceptance"],
                    },
                    "text": {"type": "string"},
                    "verify": {
                        "type": "object",
                        "description": "Required for an acceptance proposal.",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["test", "behavior", "metric", "human_judgment"],
                            },
                            "detail": {
                                "type": "string",
                                "description": "How the acceptance criterion is checked.",
                            },
                        },
                        "required": ["kind", "detail"],
                    },
                },
                "required": ["section", "text"],
            },
        },
    },
    "required": ["reply"],
}

# --- project scope (0010 u5): the same Advisor, scoped to the whole project (D2 -> a) ---
PROJECT_SCOPE_GUIDANCE = (_PROMPTS / "advisor-project-scope-guidance.txt").read_text().strip()
PROJECT_OUTPUT_CONTRACT = (_PROMPTS / "advisor-project-output-contract.txt").read_text().strip()

PROJECT_ADVISOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "The Advisor's message, shown in the rail."},
        "proposed_initiative": {
            "type": ["string", "null"],
            "description": "A PROPOSED new-initiative description (a short paragraph in the human's "
            "voice: the problem + desired outcome) — set only when the discussion has crystallised "
            "into a concrete initiative worth creating; null otherwise. A starting point, not a "
            "finished spec.",
        },
    },
    "required": ["reply"],
}

# --- BD-20: guided discovery mode -------------------------------------------------------
DISCOVERY_SCOPE_GUIDANCE = (_PROMPTS / "advisor-discovery-scope-guidance.txt").read_text().strip()
DISCOVERY_OUTPUT_CONTRACT = (_PROMPTS / "advisor-discovery-output-contract.txt").read_text().strip()

DISCOVERY_ADVISOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": "Next guided question or bridging observation — one thing, concise.",
        },
        "proposed_initiative": {
            "type": ["string", "null"],
            "description": "Set only when thinking is ready to crystallise. One paragraph: problem + desired outcome.",
        },
        "proposed_initiative_type": {
            "type": ["string", "null"],
            "enum": ["engineering", "research"],
            "description": "Set only when proposed_initiative is set.",
        },
    },
    "required": ["reply"],
}

# --- BD-22 (replaces BD-20 synthesis prompt): project synthesis with structured observations ------
SYNTHESIS_PROMPT = (_PROMPTS / "advisor-synthesis.txt").read_text().strip()

SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "advisor_observations": {
            "type": ["array", "null"],
            "description": "Exactly 1 observation: one sentence naming the issue + one sentence on why it matters. Cite IDs. Null if memory is too thin.",
            "items": {"type": "string"},
            "maxItems": 1,
        },
        "what_we_know": {
            "type": ["object", "null"],
            "description": "Cross-initiative synthesis. Null when fewer than 5 completed initiatives.",
            "properties": {
                "patterns": {
                    "type": "string",
                    "description": "Recurring themes across initiatives, citing IDs.",
                },
                "assumptions": {
                    "type": "string",
                    "description": "What was validated or invalidated. Be specific.",
                },
                "intent_alignment": {
                    "type": "string",
                    "description": "How completed work relates to the project intent.",
                },
            },
            "required": ["patterns", "assumptions", "intent_alignment"],
        },
    },
    "required": ["advisor_observations"],
}

_SHAPE_COMMAND = re.compile(r"^\s*shape\s+this(?:\s+initiative)?\s*:\s*(?P<desc>.+)", re.IGNORECASE | re.DOTALL)
MESSAGE_WINDOW_NOTE = "(showing the most recent turns)"

# BD-13: steering-ratio threshold — surface an observation when the human has resolved
# this many decisions on one initiative (agent-resolved discretion calls excluded).
STEERING_RATIO_THRESHOLD = 5

STEERING_RATIO_NOTE = """STEERING-RATIO OBSERVATION (include this naturally in your reply, \
do not skip): This initiative has had {count} decisions resolved by the human. That is at or \
above the threshold that suggests the spec's discretion section may be too narrow — these \
recurring judgment calls could have been pre-authorised. In your reply, mention this observation \
in a natural, collegial way: acknowledge the count, note that it may indicate the discretion \
section needs expansion, and offer to help draft new discretion items that would cover the \
patterns you've seen. Keep it conversational — one short paragraph at most."""


class AdvisorReply(BaseModel):
    text: str
    proposals: list[Proposal] = []

    def metadata(self) -> dict:
        """What rides along on the advisor message row — the cards the frontend renders."""
        return {"proposals": [p.model_dump() for p in self.proposals]} if self.proposals else {}


def build_system_prompt(
    state: str,
    *,
    initiative_type: InitiativeType = "engineering",
    in_project: bool = False,
    steering_count: int = 0,
) -> str:
    """Identity + spec-contract discipline + the state's mode (+ project coherence when the
    initiative is in a project) + the output contract. The state line makes the same Advisor
    shift behaviour across the lifecycle (a5); the project block widens it to reason across
    siblings (0010 a3/a5) — one Advisor, scoped (D2 -> a).

    BD-13: when steering_count >= STEERING_RATIO_THRESHOLD, injects a note instructing the
    Advisor to include a steering-ratio observation in its reply — delivered conversationally,
    not as a dashboard item (constraint item_55058254c501).

    BD-15: when initiative_type is 'research', uses research-framed mode guidance and injects
    a collaborator-register note. Underlying model, memory, and tools are unchanged."""
    is_research = initiative_type == "research"
    guidance_map = STATE_GUIDANCE_RESEARCH if is_research else STATE_GUIDANCE
    guidance = guidance_map.get(state, guidance_map["draft"])
    parts = [ADVISOR_BASE_PROMPT]
    if is_research:
        parts.append(RESEARCH_TYPE_NOTE)
    parts.append(f"This initiative is in the **{state}** state. {guidance}")
    if in_project:
        parts.append(PROJECT_COHERENCE_PROMPT)
    if steering_count >= STEERING_RATIO_THRESHOLD:
        parts.append(STEERING_RATIO_NOTE.format(count=steering_count))
    parts.append(ADVISOR_OUTPUT_CONTRACT)
    return "\n\n".join(parts)


def _render_items(label: str, items: list[SpecItem]) -> list[str]:
    confirmed = [i for i in items if i.status == "confirmed"]
    proposed = [i for i in items if i.status == "proposed"]
    out = [f"{label} (confirmed — these govern):"]
    out += [f"  - {_item_line(i)}" for i in confirmed] or ["  (none yet)"]
    if proposed:
        out.append(f"{label} (proposed — awaiting the human's confirmation):")
        out += [f"  - {_item_line(i)}" for i in proposed]
    return out


def _item_line(item: SpecItem) -> str:
    verify = getattr(item, "verify", None)
    if verify is not None:
        return f"{item.text}  [verify: {verify.kind} — {verify.detail}]"
    return item.text


def _criterion_line(c: AcceptanceCriterion) -> str:
    """Acceptance criterion with verification status for building/learning context."""
    base = _item_line(c)
    vstatus = getattr(c, "verification_status", "pending")
    evidence = getattr(c, "evidence", None)
    feedback = getattr(c, "feedback", None)
    parts = [base, f"[verification: {vstatus}]"]
    if evidence:
        parts.append(f"[evidence: {evidence[:120]}{'...' if len(evidence) > 120 else ''}]")
    if feedback and vstatus == "changes_requested":
        parts.append(f"[changes requested: {feedback}]")
    return "  ".join(parts)


def _render_spec(spec: Spec | None, short_ref: str | None = None) -> str:
    if spec is None:
        return "# CURRENT SPEC\n(no spec yet)"
    handle = f"{short_ref}: " if short_ref else ""
    in_build_or_later = spec.state in {"building", "learning", "complete"}
    lines = [
        f"# CURRENT SPEC — {handle}{spec.title} (v{spec.version}, {spec.state})",
        f"Intent: {spec.intent.strip() or '(not yet written)'}",
        "",
        *_render_items("Constraints", spec.constraints),
        "",
        *_render_items("Discretion", spec.discretion),
        "",
    ]
    if in_build_or_later and spec.acceptance:
        confirmed = [c for c in spec.acceptance if c.status == "confirmed"]
        proposed = [c for c in spec.acceptance if c.status == "proposed"]
        lines.append("Acceptance criteria (confirmed — verification status shown):")
        lines += [f"  - {_criterion_line(c)}" for c in confirmed] or ["  (none yet)"]
        if proposed:
            lines.append("Acceptance criteria (proposed — awaiting confirmation):")
            lines += [f"  - {_item_line(c)}" for c in proposed]
    else:
        lines += _render_items("Acceptance", list(spec.acceptance))
    return "\n".join(lines)


def _render_project_block(proj: ProjectContext, *, header: str, lead: str) -> str:
    """The compact project block (0010 constraint 2/3): strategic intent + one tight summary
    per (sibling) initiative. Shared by the initiative rail (siblings) and the project rail
    (the whole project)."""
    lines = [
        f"# {header} — {proj.name}",
        f"Strategic intent: {proj.intent.strip() or '(none written)'}",
        "",
        lead,
    ]
    if not proj.siblings:
        lines.append("  (none yet)")
    for s in proj.siblings:
        handle = f"{short_id(proj.prefix, s.seq)} · " if proj.prefix and s.seq else ""
        lines.append(
            f"- {s.title} [{handle}{s.initiative_id}] · {s.state} · "
            f"{s.constraint_count} confirmed constraint(s)"
        )
        lines += [f"    constraint: {c}" for c in s.constraints]
        if s.latest_decision:
            lines.append(f"    latest decision: {s.latest_decision}")
    return "\n".join(lines)


def _render_project(ctx: ConversationContext) -> str:
    """The sibling context for an initiative in a project. Empty for a standalone initiative,
    so the prompt is unchanged there (a8)."""
    if ctx.project is None:
        return ""
    return _render_project_block(
        ctx.project,
        header="PROJECT CONTEXT",
        lead="Sibling initiatives (compact summaries — retrieve specifics on demand, don't invent):",
    )


def _render_memory_hits(hits: list[ContextHit]) -> str:
    if not hits:
        return ""
    lines = ["# RELEVANT MEMORY (reuse what applies, don't contradict it):"]
    lines += [f"  - ({h.type} · {h.initiative_id}, score {h.score}): {h.text}" for h in hits]
    return "\n".join(lines)


def _render_memory(ctx: ConversationContext) -> str:
    return _render_memory_hits(ctx.memory)


def _render_history(messages: list[Message]) -> str:
    if not messages:
        return "# CONVERSATION SO FAR\n(this is the first turn)"
    speaker = {"human": "Human", "advisor": "You (Advisor)"}
    lines = [f"# CONVERSATION SO FAR {MESSAGE_WINDOW_NOTE}"]
    lines += [f"{speaker.get(m.role, m.role)}: {m.content}" for m in messages]
    return "\n".join(lines)


def build_user_message(ctx: ConversationContext) -> str:
    """The grounded context block the Advisor answers from: the current spec, the project it
    sits in (siblings, when any), relevant memory, and the windowed conversation (with the
    human's latest turn last)."""
    # The focused initiative's short id (0012 a11): so the Advisor names it as BD-7 and
    # understands the human referring to it (and its siblings) that way.
    short_ref = (
        short_id(ctx.project.prefix, ctx.initiative.seq)
        if ctx.project and ctx.project.prefix and ctx.initiative.seq
        else None
    )
    parts = [
        _render_spec(ctx.spec, short_ref),
        _render_project(ctx),
        _render_memory(ctx),
        _render_history(ctx.messages),
    ]
    return "\n\n".join(p for p in parts if p)


# --- generation -----------------------------------------------------------------------
def _parse_reply(raw: dict[str, Any]) -> AdvisorReply:
    try:
        proposals = [_coerce_proposal(p) for p in raw.get("proposals") or []]
        return AdvisorReply(text=str(raw["reply"]).strip(), proposals=proposals)
    except (KeyError, TypeError, PydanticValidationError) as e:
        raise LLMError(f"advisor output did not match the expected shape: {e}") from e


def _coerce_proposal(p: dict[str, Any]) -> Proposal:
    """Build a Proposal, defaulting verify for an acceptance card the model left bare so the
    card is still confirmable via the editing flow (which requires verify on acceptance)."""
    prop = Proposal.model_validate(p)
    if prop.section == "acceptance" and prop.verify is None:
        prop.verify = Verify(kind="behavior", detail=f"Confirm: {prop.text}")
    return prop


async def _converse(
    ctx: ConversationContext, llm: StructuredLLM, *, steering_count: int = 0
) -> AdvisorReply:
    raw = await llm.complete_structured(
        system=build_system_prompt(
            ctx.initiative.state,
            initiative_type=ctx.initiative.initiative_type,
            in_project=ctx.project is not None,
            steering_count=steering_count,
        ),
        user=build_user_message(ctx),
        schema=ADVISOR_SCHEMA,
        schema_name="advisor_turn",
    )
    return _parse_reply(raw)


def _proposals_from_draft(draft: ShapingResult) -> list[Proposal]:
    proposals = [Proposal(section="constraints", text=i.text) for i in draft.constraints]
    proposals += [Proposal(section="discretion", text=i.text) for i in draft.discretion]
    proposals += [
        Proposal(section="acceptance", text=a.text, verify=a.verify)
        for a in draft.acceptance
    ]
    return proposals


async def _shape_via_rail(
    store: SpecStore, project_id: str | None, description: str, llm: StructuredLLM
) -> AdvisorReply:
    """D2 -> c: reuse the 0006 full-draft generation, but surface the whole draft as proposal
    cards instead of persisting it. The human confirms what fits, then refines by talking."""
    draft = await shape_spec(store, description, project_id=project_id, llm=llm)
    proposals = _proposals_from_draft(draft)
    intent_note = f' Proposed intent: "{draft.intent}".' if draft.intent else ""
    reply = (
        f"I drafted a full spec from that — {len(draft.constraints)} constraints, "
        f"{len(draft.discretion)} discretion items, and {len(draft.acceptance)} acceptance "
        f"criteria.{intent_note} Review the cards and confirm what fits; we can refine the rest "
        f"by talking."
    )
    return AdvisorReply(text=reply, proposals=proposals)


def _shape_command(content: str) -> str | None:
    m = _SHAPE_COMMAND.match(content)
    desc = m.group("desc").strip() if m else None
    return desc or None


def _window_with_pending(
    history: list[Message] | None,
    *,
    content: str,
    initiative_id: str | None = None,
    project_id: str | None = None,
) -> list[Message]:
    """The bounded turn window the Advisor reasons over: the browser-sent history plus the new
    human turn, defensively capped at MESSAGE_WINDOW (a misbehaving client can't balloon the
    prompt). The frontend already windows; this is the backend's safety net (spec uvama)."""
    prior = history or []
    pending = Message(initiative_id=initiative_id, project_id=project_id, role="human", content=content.strip())
    return (prior + [pending])[-MESSAGE_WINDOW:]


async def advise(
    store: SpecStore,
    initiative_id: str,
    content: str,
    history: list[Message] | None = None,
    *,
    llm: StructuredLLM | None = None,
) -> Message:
    """One rail turn (spec uvama): ground the Advisor in the windowed history the browser sent
    plus spec + memory, generate a state-aware reply (with any proposal cards), and return it.
    Nothing is persisted — conversations live in the browser; the frontend writes the reply into
    IndexedDB. A failed LLM call (-> 502) simply yields no reply."""
    init = await store.get_initiative(initiative_id)
    if init is None:
        raise NotFoundError(f"no initiative {initiative_id}")
    if not content.strip():
        raise ValidationError("a message needs content")
    llm = llm or get_advisor_llm()

    description = _shape_command(content)
    if description is not None and init.state == "draft":
        reply = await _shape_via_rail(store, init.project_id, description, llm)
    else:
        window = _window_with_pending(history, initiative_id=initiative_id, content=content)
        ctx = await assemble_context(store, initiative_id, messages=window)
        # BD-13: check steering ratio — if the human has resolved >= 5 decisions on this
        # initiative (agent-resolved discretion calls excluded), inject the observation.
        steering_count = await store.count_human_resolved_decisions(initiative_id)
        reply = await _converse(ctx, llm, steering_count=steering_count)

    return Message(
        initiative_id=initiative_id, role="advisor", content=reply.text, metadata=reply.metadata()
    )


# --- project-level rail (0010 u5, a9/a10): the same Advisor, scoped to the project --------
def build_project_system_prompt() -> str:
    """Identity + spec-contract discipline + the project-scope mode + a reply-only contract.
    Same Advisor as the initiative rail (D2 -> a) — it just sees the whole project and speaks
    strategically rather than tactically."""
    return "\n\n".join([ADVISOR_BASE_PROMPT, PROJECT_SCOPE_GUIDANCE, PROJECT_OUTPUT_CONTRACT])


def build_project_user_message(
    project: ProjectContext, memory: list[ContextHit], messages: list[Message]
) -> str:
    """The grounded context for a project turn: the whole project (intent + every initiative's
    compact summary), project-scoped memory, and the windowed project conversation."""
    parts = [
        _render_project_block(
            project,
            header="PROJECT",
            lead="Initiatives in this project (compact summaries — retrieve specifics on demand):",
        ),
        _render_memory_hits(memory),
        _render_history(messages),
    ]
    return "\n\n".join(p for p in parts if p)


async def _converse_project(
    project: ProjectContext, memory: list[ContextHit], messages: list[Message], llm: StructuredLLM
) -> tuple[str, str | None]:
    """The project reply text plus, when the discussion has crystallised into one, a PROPOSED new
    initiative description (BD-1 u3) — null in ordinary conversation. An empty/whitespace synthesis
    is treated as none, so the rail only ever shows the action for a real proposal."""
    raw = await llm.complete_structured(
        system=build_project_system_prompt(),
        user=build_project_user_message(project, memory, messages),
        schema=PROJECT_ADVISOR_SCHEMA,
        schema_name="advisor_reply",
    )
    try:
        reply = str(raw["reply"]).strip()
    except (KeyError, TypeError) as e:
        raise LLMError(f"advisor output did not match the expected shape: {e}") from e
    pi = raw.get("proposed_initiative")
    proposed = pi.strip() if isinstance(pi, str) and pi.strip() else None
    return reply, proposed


async def advise_project(
    store: SpecStore,
    project_id: str,
    content: str,
    history: list[Message] | None = None,
    *,
    llm: StructuredLLM | None = None,
) -> tuple[Message, str | None]:
    """One turn on the PROJECT rail (a9, spec uvama): ground the Advisor in the whole project — its
    intent, every initiative's summary, project-scoped memory, and the windowed project conversation
    the browser sent — generate a strategic reply, and return it alongside any synthesised PROPOSED
    initiative description (BD-1 u3; None unless the discussion crystallised into one). Nothing is
    persisted; the frontend writes the reply into IndexedDB. A failed LLM call (-> 502) yields no reply."""
    project = await store.get_project_context(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    if not content.strip():
        raise ValidationError("a message needs content")
    llm = llm or get_advisor_llm()

    window = _window_with_pending(history, project_id=project_id, content=content)
    memory = await store.get_context(content.strip(), limit=5, project_id=project_id)
    reply, proposed_initiative = await _converse_project(project, memory, window, llm)

    return Message(project_id=project_id, role="advisor", content=reply), proposed_initiative


# --- BD-20: guided discovery mode + project synthesis -----------------------------------

async def advise_project_discovery(
    store: SpecStore,
    project_id: str,
    content: str,
    history: list[Message] | None = None,
    *,
    llm: StructuredLLM | None = None,
) -> tuple[Message, str | None, InitiativeType | None]:
    """One turn on the DISCOVERY rail (BD-20): guide the human through structured questions one at
    a time, bridge perspectives via project memory, and return a proposed initiative description +
    type when thinking crystallises. Nothing persisted; the frontend writes the reply into IndexedDB.

    Returns: (reply_message, proposed_initiative_or_none, proposed_type_or_none)
    where proposed_type is "engineering" | "research" | None."""
    project = await store.get_project_context(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    if not content.strip():
        raise ValidationError("a message needs content")
    llm = llm or get_advisor_llm()

    window = _window_with_pending(history, project_id=project_id, content=content)
    memory = await store.get_context(content.strip(), limit=5, project_id=project_id)
    system = "\n\n".join([ADVISOR_BASE_PROMPT, DISCOVERY_SCOPE_GUIDANCE, DISCOVERY_OUTPUT_CONTRACT])
    raw = await llm.complete_structured(
        system=system,
        user=build_project_user_message(project, memory, window),
        schema=DISCOVERY_ADVISOR_SCHEMA,
        schema_name="discovery_reply",
    )
    try:
        reply_text = str(raw["reply"]).strip()
    except (KeyError, TypeError) as e:
        raise LLMError(f"discovery reply did not match expected shape: {e}") from e

    pi = raw.get("proposed_initiative")
    proposed = pi.strip() if isinstance(pi, str) and pi.strip() else None
    pt = raw.get("proposed_initiative_type")
    initiative_type: InitiativeType | None = pt if pt in ("engineering", "research") else None  # type: ignore[assignment]

    return Message(project_id=project_id, role="advisor", content=reply_text), proposed, initiative_type


def _render_synthesis_user_message(
    project: "ProjectContext", memory: "list[ContextHit]", completed_count: int
) -> str:
    """Context for the synthesis LLM call: project context, memory, and the synthesis task."""
    parts = [
        _render_project_block(
            project,
            header="PROJECT",
            lead=f"Initiatives ({completed_count} complete — synthesise from completed ones):",
        ),
        _render_memory_hits(memory),
        f"# SYNTHESIS TASK\nGenerate advisor_observations (always when memory exists) and "
        f"what_we_know ({'include — ≥5 completed' if completed_count >= 5 else 'omit — fewer than 5 completed'}).",
    ]
    return "\n\n".join(p for p in parts if p)


async def synthesize_project(
    store: SpecStore,
    project_id: str,
    *,
    llm: StructuredLLM | None = None,
) -> ProjectSynthesisResponse:
    """Generate advisor observations and 'what we know' synthesis from project memory (BD-22).
    Observations are persisted to Postgres (replacing open ones) so each can be resolved into
    an initiative. 'what we know' requires ≥5 completed initiatives."""
    all_initiatives = await store.list_project_initiatives(project_id)
    completed_count = sum(1 for i in all_initiatives if i.state == "complete")

    if completed_count == 0:
        return ProjectSynthesisResponse(
            observations=[],
            what_we_know=None,
            completed_count=0,
        )

    # BD-24: only the most recently completed initiative (highest seq) may receive a new
    # observation. If it already has one (any status), skip generation to honour the
    # one-per-initiative lifetime cap.
    completed = [i for i in all_initiatives if i.state == "complete"]
    source_initiative = max(completed, key=lambda i: i.seq)
    existing = await store.get_observation_for_initiative(source_initiative.id)

    project = await store.get_project_context(project_id, sibling_limit=50)
    if project is None:
        raise NotFoundError(f"no project {project_id}")

    llm = llm or get_advisor_llm()
    query = project.intent.strip() or "patterns learnings assumptions"
    memory = await store.get_context(query, limit=12, project_id=project_id)

    raw = await llm.complete_structured(
        system=SYNTHESIS_PROMPT,
        user=_render_synthesis_user_message(project, memory, completed_count),
        schema=SYNTHESIS_SCHEMA,
        schema_name="project_synthesis",
    )

    if existing is None:
        obs_raw = raw.get("advisor_observations")
        obs_contents: list[str] = []
        if isinstance(obs_raw, list):
            obs_contents = [s.strip() for s in obs_raw if isinstance(s, str) and s.strip()]
        if obs_contents:
            await store.create_scoped_observation(project_id, source_initiative.id, obs_contents[0])

    # return ALL observations (open + resolved + rejected) so the UI shows the full picture
    observations = await store.list_observations(project_id)

    what_we_know = None
    if completed_count >= 5:
        wk_raw = raw.get("what_we_know")
        if isinstance(wk_raw, dict):
            try:
                what_we_know = WhatWeKnow(
                    patterns=str(wk_raw.get("patterns", "")).strip(),
                    assumptions=str(wk_raw.get("assumptions", "")).strip(),
                    intent_alignment=str(wk_raw.get("intent_alignment", "")).strip(),
                )
            except Exception:
                what_we_know = None

    return ProjectSynthesisResponse(
        observations=observations,
        what_we_know=what_we_know,
        completed_count=completed_count,
    )
