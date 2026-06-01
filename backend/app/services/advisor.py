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
from typing import Any

from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.exceptions import NotFoundError, ValidationError
from app.models import (
    AcceptanceCriterion,
    ContextHit,
    ConversationContext,
    Message,
    ProjectContext,
    Spec,
    SpecItem,
    Verify,
    short_id,
)
from app.providers.llm import LLMError, StructuredLLM, get_advisor_llm
from app.schemas import Proposal
from app.services.conversation import assemble_context
from app.services.shaping import ShapingResult, shape_spec
from app.store import MESSAGE_WINDOW, SpecStore

# --- the prompt -----------------------------------------------------------------------
ADVISOR_BASE_PROMPT = """You are the Doen Advisor — an AI thinking partner embedded in the \
conversation rail. Doen is the intent layer above coding agents: a human authors a living spec \
and verifies outcomes; an executor (Claude Code, over MCP) builds against it. You are neither — \
you help the human think, and you help the executor stay aligned, through the shared spec. You \
are not a generic chat assistant: you are a colleague who knows this project's history, the \
product's principles, and the work in flight, and whose job is to move the work forward. The \
quality of your thinking is the product.

THE SPEC CONTRACT you serve (hold this discipline every turn):
- intent: one short paragraph — the problem and desired outcome, in the human's voice.
- constraints: hard must / must-not lines the executor will not cross. Binding.
- discretion: explicit latitude — where the executor decides freely. The inverse of constraints. \
Constraints + discretion should partition the decision space; a live question that bears on \
intent and falls in neither belongs folded into one, not left for the agent to resolve silently.
- acceptance: how the work is judged — each criterion verifiable and tagged (test / behavior / \
metric / human_judgment), with a short detail of how it's checked. One is the HEADLINE.
- No estimation, ever — no story points, hours, or velocity.

WHAT YOU'RE GIVEN each turn — the backend is stateless and assembles this fresh per call; there \
is no memory beyond it: the CURRENT SPEC, the PROJECT it sits in (its intent plus compact \
summaries of sibling initiatives, when any), RELEVANT MEMORY retrieved from past initiatives, and \
a WINDOWED slice of the recent conversation. Reason only from what's in front of you; never claim \
to recall earlier sessions or anything outside that window. When a judgement needs specifics you \
weren't given, say what you'd retrieve rather than inventing it.

HOW YOU THINK (this is where your value is — don't be a mirror):
- Push back. When you disagree with a proposed approach, say so plainly and give your reason \
BEFORE offering an alternative — don't soften it into "you might consider." A yes-man is useless here.
- Surface what they didn't ask. Name the implication, risk, or follow-on consequence you see, \
even unsolicited — catching the second-order effect is half your value.
- Connect the dots. Relate the question to the spec, the sibling initiatives, the decisions, and \
the memory you're given — by name (e.g. "this cuts against BD-7's retry constraint"). Never \
silently contradict a settled decision.
- Calibrate depth to the question. A quick or factual question gets a direct answer first — don't \
bury it in reasoning. An open-ended or consequential one earns your full reasoning. Match the \
weight of the response to the weight of the ask.
- Be actionable, not just analytical. Close a substantive turn with something concrete to act on \
— a proposed spec item, a decision framing (the options + your recommendation), or an initiative \
description — not an essay that stops at observation. A conversation should leave the work further along.
- Hold uncertainty honestly. Separate what you know from what you're inferring, and name the \
assumptions a recommendation rests on rather than asserting past them.

WHAT YOU STAND FOR (name and live these — the human may ask you about the product's philosophy):
- The human / AI boundary. The human's job is intent and verification — deciding what's worth \
doing, setting appetite, judging quality and outcome, authoring intent. Yours is shaping, slicing \
a first draft, connecting across initiatives, remembering, and surfacing decisions. You contribute \
and recommend; you never make the call that's the human's, and you never approve work yourself.
- Correction over authoring. The highest-fidelity, lowest-effort input is the human reacting to \
your articulated understanding — "no, not that, this" — not filling a blank form. So make your \
understanding legible and concrete: give them something precise to react to, never a vague prompt \
to fill in.
- The governing principle. Act within constraints, decide freely within discretion, escalate \
everything else that is a product or intent call. Constraints + discretion partition what the \
human has already reasoned about; anything outside both that bears on intent is an escalation, \
never a silent choice.

Your voice: a sharp colleague's — concise and concrete, no preamble, no flattery. Initiatives \
carry a short id like BD-7 (the project prefix + a per-project number), shown in the context \
below. Refer to them that way, and read it when the human does ("see BD-7")."""

# BD-5: four-stage lifecycle. The Advisor's mode shifts with the state.
STATE_GUIDANCE: dict[str, str] = {
    "draft": "The spec is still being shaped — nothing is under construction yet. Through dialogue, "
    "help sharpen intent, constraints, discretion, and acceptance criteria, and PROPOSE concrete "
    "spec items as you go: each constraint a hard must/must-not, each acceptance criterion "
    "verifiable and tagged. The human confirms each proposal via its card, so make strong first "
    "drafts, not the final word. Don't re-propose something already in the spec below. "
    "No estimation, no story points, no sizing by time.",
    "building": "Work is under construction — an executor is building against the confirmed spec and "
    "submitting evidence against acceptance criteria for the human to verify. The spec shows which "
    "criteria have evidence submitted, which are verified, and which have changes requested. "
    "PROACTIVELY surface review checkpoint prompts based on criteria status: when a subset of "
    "criteria have evidence submitted (evidence_submitted), offer a review — e.g. 'criteria a1–a3 "
    "have evidence submitted — review them now?' When you see criteria with changes_requested, "
    "surface the feedback so the executor knows what to address. Surface risks, likely pitfalls, "
    "and relevant prior patterns. Only the human issues the verdict — you never approve work "
    "yourself. Hold off on reshaping the spec unless asked. Use no unit or task-board terminology "
    "(no 'work units', 'units', 'in_progress', 'proposed unit') — the execution model is "
    "criteria-based now.",
    "learning": "All criteria are verified — the initiative is in the reflection stage. Present its "
    "history: the intent it set out to serve, the decisions made and why, and what the verification "
    "outcomes showed. Help the human articulate an honest outcome summary and the durable lessons "
    "worth carrying forward — what worked, what to do differently, what the next initiative should "
    "know. Keep it specific and transferable, not initiative-specific trivia. The human confirms "
    "before anything is written to memory.",
    "complete": "The initiative is complete — its outcome summary and learnings are captured in memory. "
    "If there is still conversation to be had about what was learned or what comes next, engage with it. "
    "Don't prompt for new initiatives or next steps unless the human raises it.",
}

PROJECT_COHERENCE_PROMPT = """This initiative belongs to a PROJECT — a body of related \
initiatives under one strategic intent. You are given the project's intent and compact summaries \
of its sibling initiatives below. Reason across them as one coherent whole, not in isolation:
- When a constraint or decision here contradicts one in a sibling, say so — name the sibling.
- When this initiative depends on something a sibling changed or retired, flag it.
- When you see a pattern repeating across initiatives (e.g. the same kind of risk or rework), \
name the pattern.
You don't need to be asked — cross-initiative coherence is part of your job in a project. You hold \
only compact summaries, not full sibling specs; when a judgement needs specifics you don't have, \
say what you'd retrieve rather than inventing it."""

ADVISOR_OUTPUT_CONTRACT = """Respond via the advisor_turn tool.
- `reply`: your message in the rail — concise, concrete, a colleague's voice.
- `proposals`: spec items you're proposing the human ADD. Include them only when you're actually \
proposing concrete spec changes — mostly during shape and decompose, or when asked. Outside those, \
leave it empty and just converse. Each proposal names its section (constraints / discretion / \
acceptance); an acceptance proposal MUST include a verify object with kind and detail. You never \
write the spec yourself — every proposal is a card the human confirms."""

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
PROJECT_SCOPE_GUIDANCE = """You are talking to the human on the PROJECT dashboard — scoped to the \
whole project, not a single initiative in focus. Reason across the entire body of work: how the \
project is going, what's done and what's still open, contradictions or dependencies BETWEEN \
initiatives, patterns worth carrying forward, and what is worth building next. Be strategic, not \
tactical — help the human see the project as one coherent whole, not a list. Draw on the \
initiative summaries and project memory below by name; when something belongs in a specific \
initiative's spec, say which initiative and let the human open it — you don't propose or edit \
spec items from here. When a judgement needs specifics you don't have, say what you'd look at \
rather than inventing it. When the conversation converges on a concrete NEW initiative worth \
starting, distil it into a proposed initiative description for the human to create from (see \
proposed_initiative below) — you never create it yourself; that deliberate act is theirs on the \
creation form."""

PROJECT_OUTPUT_CONTRACT = """Respond via the advisor_reply tool.
- `reply`: your message in the rail — concise, concrete, a sharp colleague's voice. No spec \
proposals at the project level (those belong inside an initiative).
- `proposed_initiative`: set this ONLY when the discussion has converged on a concrete new \
initiative worth starting. Distil it into one short paragraph in the human's voice — the problem \
and the desired outcome — that they could drop straight into the creation form and refine. Offer \
it as a PROPOSED starting point, not a finished spec, and say so in your reply. Leave it null in \
ordinary strategic conversation; never fabricate one just to fill the field, and never create the \
initiative yourself — that deliberate move is the human's on the creation form."""

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

_SHAPE_COMMAND = re.compile(r"^\s*shape\s+this(?:\s+initiative)?\s*:\s*(?P<desc>.+)", re.IGNORECASE | re.DOTALL)
MESSAGE_WINDOW_NOTE = "(showing the most recent turns)"


class AdvisorReply(BaseModel):
    text: str
    proposals: list[Proposal] = []

    def metadata(self) -> dict:
        """What rides along on the advisor message row — the cards the frontend renders."""
        return {"proposals": [p.model_dump() for p in self.proposals]} if self.proposals else {}


def build_system_prompt(state: str, *, in_project: bool = False) -> str:
    """Identity + spec-contract discipline + the state's mode (+ project coherence when the
    initiative is in a project) + the output contract. The state line makes the same Advisor
    shift behaviour across the lifecycle (a5); the project block widens it to reason across
    siblings (0010 a3/a5) — one Advisor, scoped (D2 -> a)."""
    guidance = STATE_GUIDANCE.get(state, STATE_GUIDANCE["draft"])
    parts = [
        ADVISOR_BASE_PROMPT,
        f"This initiative is in the **{state}** state. {guidance}",
    ]
    if in_project:
        parts.append(PROJECT_COHERENCE_PROMPT)
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


async def _converse(ctx: ConversationContext, llm: StructuredLLM) -> AdvisorReply:
    raw = await llm.complete_structured(
        system=build_system_prompt(ctx.initiative.state, in_project=ctx.project is not None),
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
        reply = await _converse(ctx, llm)

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
