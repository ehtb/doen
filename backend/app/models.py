"""Domain models — the spec contract as Pydantic v2 types.

These are the durable shapes the whole app speaks in: the living Spec (one JSONB document
per initiative), its items, the parent Initiative, durable Decisions, append-only Memory,
retrieval hits, and the work-unit state machine. They carry no I/O — the repository
(app.store) persists them and the routers/services orchestrate them. API request/response
shapes live in app.schemas; persistence in app.store.
"""

from __future__ import annotations

import re
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


def slugify(title: str) -> str:
    """Kebab-case slug from a human title — the initiative id and URL key (0004)."""
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
    auth (0007). `stage` is the tracked lifecycle position, kept in sync with the spec."""

    id: str  # slug
    title: str | None = None
    stage: Stage = "discover"
    org_id: str | None = None
    owner_id: str | None = None
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
    and a relevance score (1 - cosine distance; higher is closer)."""

    initiative_id: str
    type: Literal["decision", "memory"]
    text: str
    score: float


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
