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
    Project,
    Section,
    Verify,
)


# --- initiatives ---------------------------------------------------------------------
class CreateInitiative(BaseModel):
    title: str
    project_id: str  # every initiative belongs to a project (0010, no orphan specs)


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
    """The project dashboard view (0010 a2 / 0011 a8): the project, its grouped initiatives, a
    project-wide aggregate (open decisions across all of them), and per-initiative attention
    counts keyed by initiative id. State distribution is derived on the client from the
    initiatives list."""

    project: Project
    initiatives: list[Initiative]
    open_decisions: int  # open escalations across every initiative in the project
    attention: dict[str, InitiativeAttention] = {}


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


# --- AI-assisted shaping -------------------------------------------------------------
class ShapeWithAI(BaseModel):
    description: str


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
    spec/memory, generates a reply, and persists nothing."""

    content: str
    history: list[MessageInput] = []


class Proposal(BaseModel):
    """A spec item the Advisor proposes (0009 u2). The frontend renders it as a card;
    confirming it calls the 0002 editing endpoints (the Advisor never writes the spec
    itself — constraint 4). verify_* are required only for an acceptance proposal."""

    section: Section
    text: str
    verify_kind: Literal["test", "behavior", "metric", "human_judgment"] | None = None
    verify_detail: str | None = None


class AdvisorReply(BaseModel):
    """The Advisor's reply to a rail turn (spec uvama). Just the Advisor's message — the human's
    turn already lives in the browser. Nothing here is persisted server-side; the frontend writes
    the reply into IndexedDB. `metadata` carries any proposal cards (rendered by the rail).

    BD-1 u3: on a PROJECT turn the Advisor may also synthesise the discussion into a *proposed*
    initiative description — `proposed_initiative` carries it (null otherwise). It rides here as a
    sibling of the message, deliberately NOT inside message.metadata, so it stays transient UI
    state the frontend renders a 'Create initiative from this' action for and never persists."""

    message: Message
    proposed_initiative: str | None = None


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


class OutcomeDraft(BaseModel):
    """The Advisor's draft of a learn-stage outcome (0009 a8). Returned for the human to
    correct and confirm — submitting it via SubmitLearn is what writes to memory."""

    summary: str
    learnings: str
