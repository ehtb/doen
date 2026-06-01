"""Domain models — the spec contract as Pydantic v2 types.

These are the durable shapes the whole app speaks in: the living Spec (one JSONB document
per initiative), its items, the parent Initiative, durable Decisions, append-only Memory,
retrieval hits, and the work-unit state machine. They carry no I/O — the repository
(app.store) persists them and the routers/services orchestrate them. API request/response
shapes live in app.schemas; persistence in app.store.
"""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.exceptions import InvalidTransition


# ----------------------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def slug_prefix(n: int = 5) -> str:
    """A short random alphabetical prefix for a slug. Prepended to the title-derived part so
    distinct initiatives/projects never collide on a slug (and the id doesn't leak creation
    order): `abcde-passwordless-sign-in` rather than `passwordless-sign-in-2`."""
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(n))


def slugify(title: str) -> str:
    """Kebab-case slug from a human title — the title-derived part of the id and URL key
    (0004). Prepend slug_prefix() at creation for uniqueness."""
    s = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return s or "initiative"


# ----------------------------------------------------------------------------- enums + stages
Provenance = Literal["human", "ai_proposed", "ai_confirmed_by_human"]
ItemStatus = Literal["proposed", "confirmed", "retired"]
Section = Literal["constraints", "discretion", "acceptance"]  # the editable spec sections
Stage = Literal["discover", "shape", "bet", "decompose", "implement", "verify", "learn"]
STAGES: tuple[str, ...] = (
    "discover", "shape", "bet", "decompose", "implement", "verify", "learn",
)


def is_adjacent_stage(current: str, target: str) -> bool:
    """A legal lifecycle move is exactly one step — forward, or back for rework (0004 c3).
    No skipping; no arbitrary jumps."""
    if current not in STAGES or target not in STAGES:
        return False
    return abs(STAGES.index(current) - STAGES.index(target)) == 1


# ----------------------------------------------------------------------------- spec models
class SpecItem(BaseModel):
    id: str = Field(default_factory=lambda: _id("item"))
    text: str
    provenance: Provenance = "human"
    status: ItemStatus = "proposed"  # proposed items do NOT govern agents
    created_at: str = Field(default_factory=_now)
    confirmed_at: str | None = None


class Verify(BaseModel):
    kind: Literal["test", "behavior", "metric", "human_judgment"]
    detail: str


class AcceptanceCriterion(SpecItem):
    verify: Verify


class Reference(BaseModel):
    id: str = Field(default_factory=lambda: _id("ref"))
    kind: Literal["code", "prior_initiative", "design", "doc", "external"]
    pointer: str
    note: str


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: _id("spec"))
    initiative_id: str
    version: int = 0  # 0 = unsaved; save_spec bumps to 1 on first write
    stage: Stage = "shape"
    title: str
    intent: str = ""
    constraints: list[SpecItem] = Field(default_factory=list)
    discretion: list[SpecItem] = Field(default_factory=list)
    acceptance: list[AcceptanceCriterion] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    memory_links: list[str] = Field(default_factory=list)

    def confirmed_constraints(self) -> list[SpecItem]:
        """What actually governs an agent — proposed items are not yet binding."""
        return [c for c in self.constraints if c.status == "confirmed"]


# ----------------------------------------------------------------------------- initiative
class Initiative(BaseModel):
    """The parent entity (0004): a spec, its decisions, and its work units all belong to
    one initiative. `id` is a human-readable slug. org/owner exist but are unused until
    auth (0007). `stage` is the tracked lifecycle position, kept in sync with the spec.
    `project_id` (0010) is the required link to the parent Project — every initiative belongs
    to a project; there are no orphan specs."""

    id: str  # slug
    project_id: str  # FK to projects.id — required; every initiative belongs to a project
    title: str | None = None
    stage: Stage = "discover"
    org_id: str | None = None
    owner_id: str | None = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


# ----------------------------------------------------------------------------- projects (0010)
class Project(BaseModel):
    """A group of related initiatives under a shared strategic intent (0010 constraint 1).
    A project is a context boundary for the Advisor: inside one, it reasons across the whole
    project's history. `id` is a human-readable slug derived from the name. One project per
    initiative (D1 -> a) — the link is a flat nullable FK on the initiative, not a junction."""

    id: str  # slug
    name: str
    intent: str = ""  # the strategic goal, prose
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


# ----------------------------------------------------------------------------- decisions
class Decision(BaseModel):
    id: str = Field(default_factory=lambda: _id("dec"))
    question: str
    options: list[str]
    recommendation: str | None = None
    chosen: str | None = None
    rationale: str | None = None
    raised_by: Literal["agent", "human"] = "agent"
    decided_by: str | None = None
    status: Literal["open", "resolved"] = "open"
    emitted_item_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    resolved_at: str | None = None


# ----------------------------------------------------------------------------- memory (0005)
class Memory(BaseModel):
    """An append-only record of a completed (or revisited) initiative: what it set out to
    do vs. what happened, plus learnings. Embedded for cross-initiative retrieval. Never
    edited — a revisit becomes a new row (constraint 4). The embedding is a DB column, not
    a model field (like Decision)."""

    id: str = Field(default_factory=lambda: _id("mem"))
    initiative_id: str
    summary: str
    learnings: str | None = None
    outcome: dict | None = None  # an optional structured snapshot (e.g. per-unit results)
    created_at: str = Field(default_factory=_now)


class ContextHit(BaseModel):
    """One retrieved memory snippet (0005 u3). Source-attributed so the executor can judge
    whether to trust it (constraint 5): which initiative, which kind of record, the text,
    and a relevance score (1 - cosine distance; higher is closer). `scope` (0010 constraint 4)
    marks whether a hit came from within the calling initiative's project or the global
    fallback — None when the search wasn't project-scoped."""

    initiative_id: str
    type: Literal["decision", "memory"]
    text: str
    score: float
    scope: Literal["project", "global"] | None = None


# ----------------------------------------------------------------------------- conversation (0009)
MessageRole = Literal["human", "advisor"]  # the two parties on the rail


class Message(BaseModel):
    """One turn on a conversation rail (0009 constraint 1): an individual row, never folded
    into a JSONB blob. `metadata` carries structured payloads the Advisor attaches — e.g.
    proposal cards the frontend renders (u2/u3). A message belongs to EITHER an initiative or a
    project (0010 u5: the project-level rail), never both — exactly one owner is set."""

    id: str = Field(default_factory=lambda: _id("msg"))
    initiative_id: str | None = None
    project_id: str | None = None
    role: MessageRole
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)


class SiblingSummary(BaseModel):
    """A compact, token-conscious summary of one sibling initiative in the same project
    (0010 constraint 3): enough for the Advisor to spot contradictions and patterns — title,
    stage, the headline confirmed constraints (+ their total count), and the most recent
    resolved decision — without serialising the whole sibling spec. Specifics are retrieved
    on demand via project-scoped get_context (u4)."""

    initiative_id: str
    title: str
    stage: str
    constraint_count: int = 0                              # total confirmed constraints
    constraints: list[str] = Field(default_factory=list)   # the headline confirmed constraints
    latest_decision: str | None = None                     # the most recent resolved decision


class ProjectContext(BaseModel):
    """The project a conversation is grounded in (0010 constraint 2): the strategic intent
    plus compact summaries of the sibling initiatives. Present only when the initiative
    belongs to a project — a standalone initiative carries None (a8)."""

    project_id: str
    name: str
    intent: str = ""
    siblings: list[SiblingSummary] = Field(default_factory=list)


class ConversationContext(BaseModel):
    """The explicit, bounded context assembled for an Advisor LLM call (0009 constraint 1):
    a recent-message window + the current spec + relevant memory. u2 renders this into the
    prompt; keeping it a structured object makes the windowing testable without an LLM.
    `project` (0010) widens the context to the whole project when the initiative belongs to
    one — sibling summaries the Advisor reasons across; None for a standalone initiative."""

    initiative: Initiative
    spec: Spec | None = None
    messages: list[Message] = Field(default_factory=list)  # the recent window, oldest-first
    memory: list[ContextHit] = Field(default_factory=list)
    project: ProjectContext | None = None


class Guidance(BaseModel):
    """A read-only briefing for an executor about to build a work unit (0009 u4, constraint
    5). The grounded fields (constraints / criteria / memory) come straight from the spec and
    memory corpus — never hallucinated; the Advisor adds the synthesis (briefing + pitfalls).
    The executor reads it; it never writes back. `spec_version` is part of the cache key, so a
    spec edit invalidates a stale briefing for free."""

    unit_id: str
    title: str
    scope: str
    spec_version: int
    constraints: list[str] = Field(default_factory=list)    # the confirmed rules that bind it
    criteria: list[str] = Field(default_factory=list)        # acceptance criteria it must meet
    memory: list[ContextHit] = Field(default_factory=list)   # relevant prior patterns
    briefing: str = ""                                       # the Advisor's synthesized notes
    pitfalls: list[str] = Field(default_factory=list)        # known traps to avoid


class CriterionReview(BaseModel):
    """The Advisor's independent read of the evidence for one acceptance criterion (0009 u5)."""

    criterion: str
    assessment: Literal["aligned", "partial", "gap", "concern"]
    note: str


class ReviewNotes(BaseModel):
    """The Advisor's preliminary review of a submitted unit (0009 u5, a7): evidence weighed
    against the acceptance criteria, for the human verifier. These are notes, never a verdict
    — only the human judges (no self-approval). Auto-posted to the rail on submit (D1 -> b)."""

    unit_id: str
    initiative_id: str
    title: str
    summary: str
    criteria: list[CriterionReview] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- work units (0003)
# A fixed state machine. A unit is created `proposed`; a human confirms it to `ready`
# before it's workable, and an executor can never confirm its own (no-self-confirm).
# `changes_requested` is a verdict, not a resting status: per 0003 a7 it lands the unit
# back in `in_progress` with feedback — so it is NOT a member of UnitStatus, and
# `in_verification -> in_progress` is the one allowed backward transition.
UnitStatus = Literal[
    "proposed", "ready", "in_progress", "blocked_on_decision", "in_verification", "done"
]

_UNIT_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"ready"}),                        # human confirms
    "ready": frozenset({"in_progress"}),                     # executor starts
    "in_progress": frozenset({"blocked_on_decision", "in_verification"}),
    "blocked_on_decision": frozenset({"in_progress"}),       # decision resolved -> resume
    "in_verification": frozenset({"done", "in_progress"}),   # approved / changes_requested
    "done": frozenset(),                                     # terminal
}


class CriterionResult(BaseModel):
    """One acceptance criterion, as the executor reports it on submission."""

    criterion_id: str
    result: Literal["pass", "fail", "needs_judgment"]
    evidence: str = ""


class Submission(BaseModel):
    """What the executor hands back for judgment — its output mapped to the criteria."""

    summary: str
    criteria_results: list[CriterionResult]
    artifacts: list[str] = Field(default_factory=list)
    submitted_at: str = Field(default_factory=_now)


class Verdict(BaseModel):
    """The human's judgment on a submission. Only a human writes this (no self-approval)."""

    verdict: Literal["approved", "changes_requested"]
    feedback: str = ""
    decided_by: str
    decided_at: str = Field(default_factory=_now)


class WorkUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: _id("unit"))
    spec_id: str  # the initiative_id of the spec this unit decomposes (one spec per initiative)
    title: str
    scope: str
    criterion_ids: list[str] = Field(default_factory=list)  # acceptance criteria it satisfies
    status: UnitStatus = "proposed"  # created proposed; not workable until a human confirms it
    blocked_on: str | None = None  # decision id while status == blocked_on_decision
    progress_note: str | None = None  # lightweight executor heartbeat (report_progress)
    submission: Submission | None = None  # set on submit_for_verification
    verdict: Verdict | None = None  # set by the human's verdict (u3); read by get_verification
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    def transition(self, target: UnitStatus) -> "WorkUnit":
        """Move along the fixed state machine, or raise. Every status change goes through
        here — it is the sole legality rule for a unit's lifecycle."""
        if target not in _UNIT_TRANSITIONS.get(self.status, frozenset()):
            raise InvalidTransition(self.id, self.status, target)
        self.status = target
        self.updated_at = _now()
        return self
