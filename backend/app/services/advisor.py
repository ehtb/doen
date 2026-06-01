"""The Doen Advisor (spec 0009 u2): a state-aware thinking partner on the conversation rail.

The prompt is the product. The Advisor is grounded, every turn, in four things (constraint
3): the spec-contract discipline (distilled), the current spec, relevant organisational
memory, and the recent conversation. Its *mode* shifts with the initiative's lifecycle state
(0011: draft / building / complete) — drafting spec items while a spec is in Draft, surfacing
risks and weighing submitted evidence while Building, drafting outcomes once Complete — while
never crossing the constraint/discretion boundary or making a call that belongs to the human (a9).

It reuses the 0006 LLM provider (constraint 2: one AI path) and forces a structured turn —
a `reply` plus optional `proposals` the frontend renders as cards. Proposals are never
written to the spec here; confirming a card calls the 0002 editing flow (constraint 4).

D2 -> c: "shape this initiative: <description>" is a rail command — it reuses the 0006
one-shot full-draft generation, surfacing the whole draft as proposal cards rather than
silently persisting it, so the human refines through dialogue from there.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.exceptions import NotFoundError, ValidationError
from app.models import (
    ContextHit,
    ConversationContext,
    Message,
    ProjectContext,
    Spec,
    SpecItem,
    short_id,
)
from app.providers.llm import LLMError, StructuredLLM, get_advisor_llm
from app.schemas import AdvisorTurn, Proposal
from app.services.conversation import assemble_context
from app.services.shaping import ShapingResult, shape_spec
from app.store import MESSAGE_WINDOW, SpecStore

# --- the prompt -----------------------------------------------------------------------
ADVISOR_BASE_PROMPT = """You are the Doen Advisor — an AI thinking partner embedded in the \
conversation rail of a single initiative. Doen is the intent layer above coding agents: a human \
authors a living spec and verifies outcomes; an executor (Claude Code, over MCP) builds against \
it. You are neither — you help the human think, and you help the executor stay aligned, through \
the shared spec.

The spec contract you serve (hold this discipline in every turn):
- intent: one short paragraph — the problem and desired outcome, in the human's voice.
- constraints: hard must / must-not lines the executor will not cross. Binding.
- discretion: explicit latitude — where the executor decides freely. The inverse of constraints.
  Constraints + discretion should partition the decision space; a live question that bears on \
intent and falls in neither should be folded into one, not left for the agent to resolve silently.
- acceptance: how the work is judged — each criterion verifiable and tagged (test / behavior / \
metric / human_judgment), with a short detail of how it's checked. One is the HEADLINE.
- No estimation, ever — no story points, hours, or velocity.

How you hold yourself:
- Ground every response in the CURRENT SPEC, the CONVERSATION SO FAR, and the RELEVANT MEMORY \
you're given below. When a prior initiative's pattern applies, draw on it by name; never silently \
contradict a past decision.
- The human authors intent and issues every verdict; the executor builds. You contribute, you \
don't decide. Surface options and a recommendation — never make the call that belongs to the \
human, and never approve work yourself.
- Be concise and concrete, in a sharp colleague's voice. Say what matters; skip the preamble.
- Initiatives carry a short id like BD-7 (the project prefix + a per-project number), shown in \
the context below. Refer to them that way, and read it when the human does ("see BD-7")."""

# The lifecycle is three inferred states now (0011 constraint 1). The Advisor's mode shifts with
# the state: shaping while Draft, guiding + reviewing while Building, reflecting once Complete.
STATE_GUIDANCE: dict[str, str] = {
    "draft": "The spec is still being shaped — nothing is under construction yet. Through dialogue, "
    "help sharpen intent, constraints, discretion, and acceptance, and PROPOSE concrete spec items "
    "as you go: each constraint a hard must/must-not, each acceptance criterion verifiable and "
    "tagged. When the shape is solid, help break the work into independently verifiable units, each "
    "tracing to acceptance criteria — never sized or sequenced by effort or time (no estimation). "
    "The human confirms each proposal via its card, so make strong first drafts, not the final "
    "word. Don't re-propose something already in the spec below.",
    "building": "Work is under construction — an executor is building against the confirmed spec and "
    "submitting units for judgment. Surface risks, likely pitfalls, and relevant prior patterns; "
    "point to the constraints that bind this work and the acceptance criteria it must satisfy. When "
    "a unit is submitted, review its evidence against each criterion — where it aligns, where there "
    "are gaps, what concerns remain — as preliminary notes for the human verifier. Only the human "
    "issues the verdict, and you never approve work yourself. You guide; you don't write the code, "
    "and you hold off on reshaping the spec unless asked.",
    "complete": "The initiative is done — every unit is verified and the work is closing out. From "
    "its history — the intent, the decisions made and why, the verification outcomes — draft a "
    "concise outcome summary and the key learnings worth remembering. The human corrects and "
    "confirms before anything is written to memory.",
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
acceptance); an acceptance proposal MUST include verify_kind and verify_detail. You never write \
the spec yourself — every proposal is a card the human confirms."""

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
                    "verify_kind": {
                        "type": "string",
                        "enum": ["test", "behavior", "metric", "human_judgment"],
                        "description": "Required for an acceptance proposal.",
                    },
                    "verify_detail": {
                        "type": "string",
                        "description": "How the acceptance criterion is checked.",
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
rather than inventing it."""

PROJECT_OUTPUT_CONTRACT = """Respond via the advisor_reply tool with `reply`: your message in the \
rail — concise, concrete, a sharp colleague's voice. No spec proposals at the project level."""

PROJECT_ADVISOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "The Advisor's message, shown in the rail."},
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


def _render_spec(spec: Spec | None, short_ref: str | None = None) -> str:
    if spec is None:
        return "# CURRENT SPEC\n(no spec yet)"
    handle = f"{short_ref}: " if short_ref else ""
    lines = [
        f"# CURRENT SPEC — {handle}{spec.title} (v{spec.version}, {spec.state})",
        f"Intent: {spec.intent.strip() or '(not yet written)'}",
        "",
        *_render_items("Constraints", spec.constraints),
        "",
        *_render_items("Discretion", spec.discretion),
        "",
        *_render_items("Acceptance", list(spec.acceptance)),
    ]
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
    if prop.section == "acceptance" and prop.verify_kind is None:
        prop.verify_kind = "behavior"
        prop.verify_detail = prop.verify_detail or f"Confirm: {prop.text}"
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
        Proposal(
            section="acceptance",
            text=a.text,
            verify_kind=a.verify.kind,
            verify_detail=a.verify.detail,
        )
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


async def advise(
    store: SpecStore,
    initiative_id: str,
    content: str,
    *,
    llm: StructuredLLM | None = None,
) -> AdvisorTurn:
    """One rail turn: ground the Advisor, generate a state-aware reply (with any proposal
    cards), and persist the exchange. The human turn + Advisor reply are stored only after a
    successful generation, so a failed LLM call (-> 502) leaves no orphan message."""
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
        ctx = await assemble_context(store, initiative_id, pending_human=content)
        reply = await _converse(ctx, llm)

    human = await store.append_message(initiative_id, "human", content.strip())
    advisor = await store.append_message(
        initiative_id, "advisor", reply.text, metadata=reply.metadata()
    )
    return AdvisorTurn(human=human, advisor=advisor)


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
) -> str:
    raw = await llm.complete_structured(
        system=build_project_system_prompt(),
        user=build_project_user_message(project, memory, messages),
        schema=PROJECT_ADVISOR_SCHEMA,
        schema_name="advisor_reply",
    )
    try:
        return str(raw["reply"]).strip()
    except (KeyError, TypeError) as e:
        raise LLMError(f"advisor output did not match the expected shape: {e}") from e


async def advise_project(
    store: SpecStore,
    project_id: str,
    content: str,
    *,
    llm: StructuredLLM | None = None,
) -> AdvisorTurn:
    """One turn on the PROJECT rail (a9): ground the Advisor in the whole project — its intent,
    every initiative's summary, project-scoped memory, and the project conversation — generate a
    strategic reply, and persist the exchange. Persisted only after a successful generation, so
    a failed LLM call (-> 502) leaves no orphan message."""
    project = await store.get_project_context(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    if not content.strip():
        raise ValidationError("a message needs content")
    llm = llm or get_advisor_llm()

    messages = await store.list_project_messages(project_id, limit=MESSAGE_WINDOW)
    pending = Message(project_id=project_id, role="human", content=content.strip())
    window = (messages + [pending])[-MESSAGE_WINDOW:]
    memory = await store.get_context(content.strip(), limit=5, project_id=project_id)
    reply = await _converse_project(project, memory, window, llm)

    human = await store.append_project_message(project_id, "human", content.strip())
    advisor = await store.append_project_message(project_id, "advisor", reply)
    return AdvisorTurn(human=human, advisor=advisor)
