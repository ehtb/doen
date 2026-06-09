"""Domain models — the spec contract as Pydantic v2 types.

These are the durable shapes the whole app speaks in: the living Spec (one JSONB document
per initiative), its items, the parent Initiative, durable Decisions, append-only Memory,
and retrieval hits. They carry no I/O — the repository (app.store) persists them (with the
exception of Message, which is browser-local) and the routers/services orchestrate them.
API request/response shapes live in app.schemas; persistence in app.store.
"""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


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



def derive_prefix(name: str) -> str:
    """A short uppercase project prefix from its name's first letters (0012 u5): 'Build Doen' ->
    'BD'. With the per-project sequence it forms the short id (BD-7). Single-word names fall back
    to the first two letters; store.create_project disambiguates collisions."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return "P"
    initials = "".join(w[0] for w in words).upper()
    return (initials if len(initials) >= 2 else words[0][:2].upper()) or "P"


def short_id(prefix: str, seq: int) -> str:
    """The canonical short identifier shown to humans and understood by the Advisor: BD-7 (0012
    u5 / constraint 8). Prefix from the project, number from the initiative's per-project seq."""
    return f"{prefix}-{seq}"


def short_slug(prefix: str, seq: int, title: str | None) -> str:
    """The URL key (0012 a10): the short id, lowercased, + a human-readable title slug —
    bd-7-csv-export. Decorative beyond the prefix+number, which is what actually resolves."""
    return f"{prefix.lower()}-{seq}-{slugify(title or 'initiative')}"


# ----------------------------------------------------------------------------- enums + lifecycle
Provenance = Literal["human", "ai_proposed", "ai_confirmed_by_human"]
ItemStatus = Literal["proposed", "confirmed", "retired"]
Section = Literal["constraints", "discretion", "acceptance"]  # the editable spec sections

# The lifecycle (BD-5): four states — Draft, Building, Learning, Complete — derived from
# criteria verification state, not work units. State is stored on the initiative row and
# updated by store methods as criteria and learn records change.
State = Literal["draft", "building", "learning", "complete"]
STATES: tuple[str, ...] = ("draft", "building", "learning", "complete")

# BD-15: two initiative types. Set at creation; immutable thereafter.
InitiativeType = Literal["engineering", "research"]


# ----------------------------------------------------------------------------- spec models
AdvisorClassification = Literal["confident", "flagged", "uncertain"]
AdvisorVerdict = Literal["pass", "needs_your_eye", "borderline"]
ShapingStatus = Literal["pending", "complete", "error"]


class SpecItem(BaseModel):
    id: str = Field(default_factory=lambda: _id("item"))
    text: str
    provenance: Provenance = "human"
    status: ItemStatus = "proposed"  # proposed items do NOT govern agents
    created_at: str = Field(default_factory=_now)
    confirmed_at: str | None = None
    # BD-14: Advisor self-review classification — set after shaping, before human confirmation.
    advisor_classification: AdvisorClassification | None = None
    advisor_classification_reason: str | None = None


class Verify(BaseModel):
    kind: Literal["test", "behavior", "metric", "human_judgment"]
    detail: str


VerificationStatus = Literal["pending", "evidence_submitted", "verified", "changes_requested"]
CriterionVerdict = Literal["approved", "changes_requested"]


class AcceptanceCriterion(SpecItem):
    verify: Verify
    # BD-5 u2: criteria-as-tracking fields — set by submit_evidence and human verdict actions
    verification_status: VerificationStatus = "pending"
    evidence: str | None = None
    verdict: CriterionVerdict | None = None
    feedback: str | None = None
    # BD-14: Advisor preliminary verification verdict — set after evidence submission.
    advisor_preliminary_verdict: AdvisorVerdict | None = None
    advisor_preliminary_notes: str | None = None


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
    state: State = "draft"  # inferred lifecycle (0011); mirrored from the initiative
    initiative_type: InitiativeType = "engineering"  # BD-15: mirrored from initiative row
    title: str
    intent: str = ""
    constraints: list[SpecItem] = Field(default_factory=list)
    discretion: list[SpecItem] = Field(default_factory=list)
    acceptance: list[AcceptanceCriterion] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    memory_links: list[str] = Field(default_factory=list)
    # BD-14: Advisor self-review outputs — set after shaping and after evidence submission.
    shaping_review_synthesis: str | None = None
    verification_synthesis: str | None = None
    # Background shaping: "pending" while the LLM fills the spec, "complete" when done.
    shaping_status: ShapingStatus = "complete"
    # The description that triggered creation — retained so retry-shaping has something to work from.
    original_description: str | None = None

    def confirmed_constraints(self) -> list[SpecItem]:
        """What actually governs an agent — proposed items are not yet binding."""
        return [c for c in self.constraints if c.status == "confirmed"]


# ----------------------------------------------------------------------------- initiative
class Initiative(BaseModel):
    """The parent entity (0004): a spec, its decisions, and its work units all belong to
    one initiative. `id` is a human-readable slug. org/owner exist but are unused until
    auth (0007). `state` is the inferred lifecycle position (0011), recomputed from the work
    units + learn record — never advanced by hand. `project_id` (0010) is the required link to
    the parent Project — every initiative belongs to a project; there are no orphan specs."""

    id: str  # slug — the stable internal key everything references
    project_id: str  # FK to projects.id — required; every initiative belongs to a project
    seq: int = 0  # immutable per-project sequence (0012 u5): with the project prefix -> BD-7
    title: str | None = None
    state: State = "draft"
    initiative_type: InitiativeType = "engineering"  # BD-15: set at creation, immutable
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
    prefix: str = ""  # short handle for the project's initiatives (0012 u5): 'BD' -> BD-7
    intent: str = ""  # the strategic goal, prose
    onboarding_dismissed: bool = False  # BD-9: server-side dismissal of the onboarding hint
    archived: bool = False  # BD-11: derived from archived_at IS NOT NULL; never manually set
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
    # BD-13: "human" = resolved by the human on the steering rail;
    # "agent" = intercepted by the Discretion Auditor as within-discretion.
    resolver_type: Literal["human", "agent"] | None = None
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
    initiative_type: InitiativeType = "engineering"  # BD-15: type of the source initiative
    created_at: str = Field(default_factory=_now)
    last_verified_at: str | None = None  # BD-12: NULL = never verified against codebase


# ----------------------------------------------------------------------------- drift reports (BD-12)
DriftReportStatus = Literal["pending", "approved", "dismissed", "initiative_created"]


class DriftReport(BaseModel):
    """An agent-reported discrepancy between a memory entry and the live codebase (BD-12).
    Persisted as a durable row and surfaced as a human-actionable attention item. Memory is
    only mutated after explicit human approval — never auto-updated on agent report alone.
    `quality` carries the LLM-as-judge result (JudgeResult serialised) so per-dimension
    scores are queryable without schema changes."""

    id: str = Field(default_factory=lambda: _id("dr"))
    memory_id: str
    initiative_id: str | None = None  # the initiative from which drift was reported (context)
    current_evidence: str
    is_obsolete: bool = False
    status: DriftReportStatus = "pending"
    resolution_note: str | None = None
    quality: dict | None = None  # BD-12: JudgeResult as JSONB; None if judge was skipped
    created_at: str = Field(default_factory=_now)
    resolved_at: str | None = None


class ContextHit(BaseModel):
    """One retrieved memory snippet (0005 u3). Source-attributed so the executor can judge
    whether to trust it (constraint 5): which initiative, which kind of record, the text,
    and a relevance score (1 - cosine distance; higher is closer). `scope` (0010 constraint 4)
    marks whether a hit came from within the calling initiative's project or the global
    fallback — None when the search wasn't project-scoped. `has_pending_drift` (BD-12) warns
    the executor that another agent has already flagged this memory entry as potentially wrong —
    treat it with extra scepticism and verify before acting on it. `initiative_type` (BD-15)
    is present for memory hits so the executor knows whether the learning came from a research
    or engineering initiative; None for decision hits. `heuristic_id` (BD-17) is set for
    heuristic-type hits — the stable ID to cite in a confident classification. `superseded_by`
    (BD-17) is set when the heuristic has been superseded — its presence disqualifies 'confident'
    classification per constraint item_226144412674."""

    initiative_id: str
    type: Literal["decision", "memory", "heuristic"]
    text: str
    score: float
    scope: Literal["project", "global"] | None = None
    has_pending_drift: bool = False  # BD-12: a pending drift report exists for this memory entry
    initiative_type: str | None = None  # BD-15: "engineering" or "research" for memory hits
    # BD-17: heuristic-specific fields — None for decision/memory hits
    heuristic_id: str | None = None     # the heuristic's own id; cite this in confident reasons
    superseded_by: str | None = None    # initiative_id that superseded this heuristic


# ----------------------------------------------------------------------------- observations (BD-22, BD-24)
ObservationStatus = Literal["open", "resolved", "rejected"]


class Observation(BaseModel):
    """A persisted advisor observation for a project (BD-22). Generated by the synthesis LLM
    call and stored as individual records so each can be resolved into an initiative.
    `resolved_initiative_id` is set when the human creates an initiative from this observation.
    BD-24: `source_initiative_id` links to the initiative the observation was generated for;
    `rejected` status lets a human dismiss without acting."""

    id: str = Field(default_factory=lambda: _id("obs"))
    project_id: str
    content: str
    status: ObservationStatus = "open"
    source_initiative_id: str | None = None
    resolved_initiative_id: str | None = None
    created_at: str = Field(default_factory=_now)


# ----------------------------------------------------------------------------- heuristics (BD-17)
class Heuristic(BaseModel):
    """An append-only actionable rule extracted from a completed initiative (BD-17). Stored as a
    distinct memory type (constraint item_5358c84c18fc) — never folded into Memory records.
    Supersession is recorded by setting superseded_by; the old row stays readable (item_580f56224a2b).
    `replaces` holds the heuristic_id this entry supersedes — bi-directional chain (item_47ba758192ea)."""

    id: str = Field(default_factory=lambda: _id("heur"))
    initiative_id: str
    project_id: str | None = None
    rule: str
    tags: list[str] = Field(default_factory=list)
    superseded_by: str | None = None   # initiative_id that superseded this entry
    replaces: str | None = None        # heuristic_id this entry replaces
    created_at: str = Field(default_factory=_now)


# ----------------------------------------------------------------------------- conversation (0009)
MessageRole = Literal["human", "advisor"]  # the two parties on the rail


class Message(BaseModel):
    """One turn on a conversation rail (0009 constraint 1): a session data carrier for Advisor
    turns; browser-local and not persisted in Postgres (spec uvama). `metadata` carries
    structured payloads the Advisor attaches — e.g. proposal cards the frontend renders (u2/u3).
    A message belongs to EITHER an initiative or a project (0010 u5: the project-level rail),
    never both — exactly one owner is set."""

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
    lifecycle state, the headline confirmed constraints (+ their total count), and the most
    recent resolved decision — without serialising the whole sibling spec. Specifics are
    retrieved on demand via project-scoped get_context (u4)."""

    initiative_id: str
    seq: int = 0                                           # per-project number -> short id (BD-7)
    title: str
    state: str
    constraint_count: int = 0                              # total confirmed constraints
    constraints: list[str] = Field(default_factory=list)   # the headline confirmed constraints
    latest_decision: str | None = None                     # the most recent resolved decision


class ProjectContext(BaseModel):
    """The project a conversation is grounded in (0010 constraint 2): the strategic intent
    plus compact summaries of the sibling initiatives. Present only when the initiative
    belongs to a project — a standalone initiative carries None (a8)."""

    project_id: str
    name: str
    prefix: str = ""  # the project's short handle, so the Advisor can render BD-7 (0012 a11)
    intent: str = ""
    siblings: list[SiblingSummary] = Field(default_factory=list)


class InitiativeAttention(BaseModel):
    """What needs the human on one initiative (0011 a8): the attention indicators the project
    screen shows per card, so where work is waiting is visible without opening a spec."""

    proposed_items: int = 0      # ai_proposed spec items awaiting confirm / reject
    open_decisions: int = 0      # escalations awaiting a verdict
    criteria_to_verify: int = 0  # acceptance criteria with evidence_submitted awaiting verdict (BD-7)
    drift_reports: int = 0       # pending drift reports attributed to this initiative's memory (BD-12)
    is_shaping: bool = False     # spec is being drafted in the background (shaping_status=pending)

    @property
    def total(self) -> int:
        return self.proposed_items + self.open_decisions + self.criteria_to_verify + self.drift_reports


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


