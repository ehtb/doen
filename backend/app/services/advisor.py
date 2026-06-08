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

# BD-15: research-specific mode guidance — investigation framing, no executor/MCP references.
STATE_GUIDANCE_RESEARCH: dict[str, str] = {
    "draft": "This is a RESEARCH initiative — the goal is a well-reasoned conclusion, not shipped code. "
    "Help the human sharpen the research question (intent), the methodological constraints, the "
    "investigation latitude (discretion), and the success criteria that will tell them when the "
    "question is answered. PROPOSE concrete spec items: each constraint a hard scope or method "
    "boundary, each criterion a verifiable finding or conclusion. No estimation, no story points. "
    "Think like a research collaborator, not a delivery partner.",
    "building": "This initiative is INVESTIGATING — the human is gathering findings and submitting them "
    "against the success criteria. Surface the angles they may not have covered, flag contradictions "
    "between emerging findings and the spec's constraints, and help them decide when a criterion's "
    "evidence is strong enough. When criteria have findings submitted, offer to review them: "
    "'criteria C1–C2 have findings submitted — want to discuss whether they satisfy the criteria?' "
    "Lean toward a recommendation where the evidence warrants one. No code execution, no MCP tooling "
    "— findings come from the conversation rail and the human's own investigation.",
    "learning": "All findings are verified — the investigation is closing. Help the human articulate "
    "what the investigation discovered against what they set out to answer, the key decisions and "
    "methodology choices that shaped the result, and the durable lessons worth carrying forward — "
    "what the next initiative in this space should know. Keep it transferable, not investigation trivia. "
    "The human confirms before anything is written to memory.",
    "complete": "The investigation is complete — its findings and learnings are captured in memory. "
    "If there is still conversation to be had about what was learned or what it implies for future work, "
    "engage with it. Don't prompt for follow-on initiatives unless the human raises it.",
}

# BD-15: Advisor identity prefix adapted per initiative type.
RESEARCH_TYPE_NOTE = (
    "This is a RESEARCH initiative — your register is a research collaborator's, not a "
    "delivery partner's. Offer angles, surface contradictions in the evidence, and lean "
    "toward a recommendation where the findings support one. No code execution, no MCP guidance."
)

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

# --- BD-20: guided discovery mode -------------------------------------------------------
DISCOVERY_SCOPE_GUIDANCE = """You are in GUIDED DISCOVERY MODE on the project page — not the \
general strategic rail. The human does not yet have a formed initiative; they have an observation, \
hunch, or fuzzy direction. Your job is to guide them from that starting point to a shaped idea \
through conversation, one question at a time.

QUESTION SEQUENCE — draw out these five areas in roughly this order:
1. The observed problem or signal they are sensing
2. Who experiences it — the people or system affected
3. How the problem is handled today — current workarounds and why they fall short
4. What a good outcome would look like — what changes if this is solved
5. The smallest thing to build or learn that would confirm or challenge this direction

You do NOT present this list. You ask EXACTLY ONE question per turn and wait for the answer before \
proceeding. When an answer already covers a later area, acknowledge it and move to the next gap. \
If the human opens with an observation, begin immediately with the first natural follow-up question.

CROSS-PERSPECTIVE BRIDGING: As the conversation unfolds, draw on the project memory you are given \
to bridge perspectives without being asked.
- When the human describes a user-facing problem, surface a relevant technical constraint or learning \
from memory — name the source initiative.
- When the human raises a technical concern, connect it to product impact via the project intent.
Cite specific initiatives you see in the context. Never fabricate patterns."""

DISCOVERY_OUTPUT_CONTRACT = """Respond via the discovery_reply tool.
- `reply`: your next guided question, bridging observation, or acknowledgement — concise, one thing. \
Never list multiple questions or dump a summary of what's been collected.
- `proposed_initiative`: set ONLY when the five areas are sufficiently covered AND the thinking is \
clear enough to be shaped. Distil it into one short paragraph in the human's voice — problem + desired \
outcome. Signal in your reply that the thinking is ready ("I think we have enough — want to create \
an initiative from this?"). Null in every other turn.
- `proposed_initiative_type`: "research" or "engineering" — set only when `proposed_initiative` is \
set. "research" when the conversation points to investigating and validating before building; \
"engineering" when it points to building directly."""

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
SYNTHESIS_PROMPT = """You are the Doen Advisor generating a project synthesis from completed initiative memory.

OBSERVATIONS — 1 to 3 specific, actionable signals the team should address next. \
Each observation: one sentence naming the pattern, risk, or gap; one sentence on why it matters now. \
Cite initiative IDs. Return null if memory is too thin to draw meaningful conclusions.

WHAT WE KNOW (only when ≥5 completed initiatives are present):
  patterns: recurring themes across initiatives (cite IDs)
  assumptions: what was validated and what was invalidated, with specifics
  intent_alignment: how completed work maps to the project's stated intent

Rules:
- Synthesise only from the provided context. Never fabricate initiative IDs or learnings.
- Specific beats general: "BD-3 and BD-7 both hit Redis eviction" beats "reliability is a theme."
- Sparse memory: be brief and honest, not padded.
- Fewer than 5 completed initiatives: return what_we_know as null."""

SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "advisor_observations": {
            "type": ["array", "null"],
            "description": "1–3 observations. Each: one sentence naming the issue + one sentence on why it matters. Cite IDs. Null if memory is too thin.",
            "items": {"type": "string"},
            "maxItems": 3,
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

    obs_raw = raw.get("advisor_observations")
    obs_contents: list[str] = []
    if isinstance(obs_raw, list):
        obs_contents = [s.strip() for s in obs_raw if isinstance(s, str) and s.strip()]

    await store.replace_open_observations(project_id, obs_contents)
    # return ALL observations (open + resolved) so the UI shows the full picture
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
