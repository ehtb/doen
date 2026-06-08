"""API request/response models — the HTTP boundary's shapes.

Distinct from app.models (the durable domain) on purpose: these describe what a client
sends and gets back. They reference domain models where a response embeds one (e.g. the
Learn review), but the request bodies are their own thing — a router never takes a raw
domain model off the wire except where a full Spec round-trips (PUT /specs/{id}).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.config import DEV_USER_ID
from app.models import (
    Decision,
    Initiative,
    InitiativeAttention,
    Memory,
    Message,
    MessageRole,
    Observation,
    Project,
    Section,
    Verify,
)


# --- initiatives ---------------------------------------------------------------------
class CreateInitiative(BaseModel):
    title: str
    project_id: str  # every initiative belongs to a project (0010, no orphan specs)
    # BD-15: user-selected type; defaults to engineering when omitted.
    initiative_type: Literal["engineering", "research"] = "engineering"


# --- projects (0010) -----------------------------------------------------------------
class CreateProject(BaseModel):
    name: str
    intent: str = ""  # the strategic goal, prose
    # 0013 u2: the short handle (BD) for this project's initiatives. Optional — auto-derived from
    # the name when omitted; a collision is disambiguated by suffixing (BD, BD2, …).
    prefix: str | None = None


class UpdateProject(BaseModel):
    # 0013 u2: inline editing from the project dashboard. Every field optional — a PATCH carries
    # only what changed; intent is what the inline editor sends.
    intent: str | None = None


class AssignProject(BaseModel):
    project_id: str  # move to a (different) project; there is no detach (no orphan specs)


class ArchiveInitiative(BaseModel):
    # 0013 follow-up: "rejected" from draft, "archived" from building/complete — same mechanism,
    # different label. Free text is allowed so a future UI can carry a richer rationale.
    reason: str = "archived"


class ProjectDashboard(BaseModel):
    """The project dashboard view (0010 a2 / 0011 a8 / BD-12): the project, its grouped
    initiatives, project-wide aggregates (open decisions + pending drift reports), and
    per-initiative attention counts keyed by initiative id. State distribution is derived on
    the client from the initiatives list."""

    project: Project
    initiatives: list[Initiative]
    open_decisions: int  # open escalations across every initiative in the project
    pending_drift_reports: int = 0  # BD-12: pending drift reports across all project memory
    attention: dict[str, InitiativeAttention] = {}
    onboarding_prompt: str = ""  # BD-9: the setup prompt from server config (empty = not set)


# --- onboarding (BD-9) ---------------------------------------------------------------
class OnboardingStatus(BaseModel):
    """Returned by GET /projects/{id}/onboarding: whether the hint is dismissed and the
    copyable prompt the executor should paste to trigger setup_project."""

    dismissed: bool
    prompt: str  # the setup prompt to copy into the executor


# --- steering rail -------------------------------------------------------------------
class ResolveDecision(BaseModel):
    chosen: str
    rationale: str
    decided_by: str = DEV_USER_ID  # single dev user this slice; auth replaces this


# --- spec authoring ------------------------------------------------------------------
# The `version` on each request is the optimistic lock surfaced to the editor: the version
# the human last saw. save_spec re-checks it under a row lock, so a stale edit is rejected
# (409) rather than clobbering a concurrent change.
class AddItem(BaseModel):
    section: Section
    text: str
    version: int
    verify: Verify | None = None  # required iff section == "acceptance"
    # How the item is born. "human" (default) = authored by the human, confirmed on the spot.
    # "ai_proposed" = accepting one of the Advisor's proposal cards (0009 a3): it lands as a
    # proposed item the human still confirms via the normal flow — the Advisor never writes
    # a governing item directly (0009 constraint 4).
    provenance: Literal["human", "ai_proposed"] = "human"


class EditItem(BaseModel):
    text: str
    version: int


class ItemVersion(BaseModel):
    version: int


class ConfirmAll(BaseModel):
    version: int
    section: Section | None = None  # None = every section


# --- criteria verification (BD-5 u3) -------------------------------------------------
class CriterionVerdictBody(BaseModel):
    verdict: Literal["approved", "changes_requested"]
    feedback: str | None = None


# BD-15: evidence submission from the conversation rail (no MCP required for research).
class SubmitCriterionEvidence(BaseModel):
    evidence: str


# --- AI-assisted shaping -------------------------------------------------------------
class ShapeWithAI(BaseModel):
    description: str
    # BD-15: user-selected type sent with the creation request.
    initiative_type: Literal["engineering", "research"] = "engineering"


# --- conversation rail ---------------------------------------------------------------
class MessageInput(BaseModel):
    """One prior turn the browser replays into an Advisor call. Conversations are browser-local
    (spec uvama): the backend never stores these — it reads the window only to build the prompt,
    then discards it. Lean by design (role + content); proposal metadata stays client-side."""

    role: MessageRole
    content: str


class AdvisorRequest(BaseModel):
    """A rail turn (spec uvama): the human's new message plus the windowed slice of recent history
    the browser holds in IndexedDB. The backend assembles the prompt from `history` + `content` +
    spec/memory, generates a reply, and persists nothing.

    BD-20: `mode` selects general strategic conversation (default) or guided discovery (sequential
    questions from observation to shaped initiative)."""

    content: str
    history: list[MessageInput] = []
    mode: Literal["general", "discovery"] = "general"


class Proposal(BaseModel):
    """A spec item the Advisor proposes (0009 u2). The frontend renders it as a card;
    confirming it calls the 0002 editing endpoints (the Advisor never writes the spec
    itself — constraint 4). verify is required only for an acceptance proposal."""

    section: Section
    text: str
    verify: Verify | None = None


class AdvisorReply(BaseModel):
    """The Advisor's reply to a rail turn (spec uvama). Just the Advisor's message — the human's
    turn already lives in the browser. Nothing here is persisted server-side; the frontend writes
    the reply into IndexedDB. `metadata` carries any proposal cards (rendered by the rail).

    BD-1 u3: on a PROJECT turn the Advisor may also synthesise the discussion into a *proposed*
    initiative description — `proposed_initiative` carries it (null otherwise). It rides here as a
    sibling of the message, deliberately NOT inside message.metadata, so it stays transient UI
    state the frontend renders a 'Create initiative from this' action for and never persists.

    BD-20: `proposed_initiative_type` is set alongside `proposed_initiative` in discovery mode
    when the Advisor can infer whether the initiative is engineering or research."""

    message: Message
    proposed_initiative: str | None = None
    proposed_initiative_type: Literal["engineering", "research"] | None = None


# --- BD-20: project synthesis -----------------------------------------------------------

class WhatWeKnow(BaseModel):
    """BD-20: cross-initiative synthesis with three required categories — present only when
    ≥5 completed initiatives exist in the project."""

    patterns: str       # recurring themes across initiatives, citing IDs
    assumptions: str    # validated and invalidated assumptions with specifics
    intent_alignment: str  # how completed work relates to the project's stated intent


class ProjectSynthesisResponse(BaseModel):
    """BD-22: observations are now persisted records with resolve-to-initiative flow.
    `observations` is the current list (open first, then resolved) for the project.
    `what_we_know` is null when fewer than 5 completed initiatives exist."""

    observations: list[Observation]
    what_we_know: WhatWeKnow | None
    completed_count: int


class ResolveObservationRequest(BaseModel):
    """BD-22: mark an observation as resolved and link it to the created initiative."""
    initiative_id: str


# --- learn stage ---------------------------------------------------------------------
class LearnReview(BaseModel):
    initiative: Initiative
    intent: str
    decisions: list[Decision]  # resolved only — the reasoning behind what shipped
    memory: list[Memory]


class SubmitLearn(BaseModel):
    summary: str
    learnings: str | None = None
    outcome: dict | None = None
    rationale_claims: list["RationaleClaim"] = []  # BD-13: human-confirmed cause-effect claims


class RationaleClaim(BaseModel):
    """BD-13: a single cause-effect rationale claim traceable to a specific decision or
    criterion record. The Advisor drafts these; the human confirms/edits before memory write.
    No claim may reference a source ID that is not present in the initiative's actual record."""

    claim: str
    source_id: str  # a decision ID (dec_…) or criterion ID (item_…)
    source_type: Literal["decision", "criterion"]


class OutcomeDraft(BaseModel):
    """BD-13 enriched learn-stage draft (0009 a8). Returned for the human to correct and
    confirm — submitting via SubmitLearn is what writes to memory. `rationale_claims` carries
    cause-effect claims each traceable to a specific decision or criterion record; the human
    must confirm these before they enter long-term memory (constraint item_b3048b678ce4)."""

    summary: str
    learnings: str
    rationale_claims: list[RationaleClaim] = []


# --- BD-17: heuristic extraction (Learn stage) ---------------------------------------

class HeuristicProposal(BaseModel):
    """One proposed heuristic extracted from a completed initiative (BD-17). The Advisor
    drafts these; the human confirms/removes before any heuristic enters long-term memory
    (constraint item_a743fde4bc87)."""

    rule: str           # the actionable heuristic text
    tags: list[str] = []
    # When this heuristic supersedes an existing one: the ID of the heuristic it replaces.
    replaces: str | None = None


class HeuristicDraftResult(BaseModel):
    """BD-17: the Advisor's proposed heuristics for the human to review before memory write."""

    initiative_id: str
    proposals: list[HeuristicProposal]


class ConfirmHeuristics(BaseModel):
    """BD-17: the human's confirmed heuristics to write to long-term memory. `proposals`
    contains only the heuristics the human accepted (may be a subset of the draft). Each
    confirmed heuristic with `replaces` set will supersede the referenced prior entry.
    `agents_md_path` is the optional path to agents.md for the append/supersede update."""

    proposals: list[HeuristicProposal]
    agents_md_path: str | None = None  # absolute path to agents.md for append/supersede write
