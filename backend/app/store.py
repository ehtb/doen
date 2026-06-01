"""
Doen spec store — Pydantic v2 models + async data layer.

Architecture:
  Postgres = source of truth (durable). Spec stored as a single JSONB document.
  Redis    = derived hot state: read-through cache + real-time coordination.
             Always rebuildable from Postgres. Never the other way round.

Relational surface is intentionally tiny:

  initiatives (id pk, org_id, owner_id, appetite text, stage, created_at)
  specs       (initiative_id pk, version int, doc jsonb, updated_at)
  decisions   (id pk, initiative_id, payload jsonb, status, embedding vector(1536),
               created_at, resolved_at)
  memory      (id pk, initiative_id, summary, outcome jsonb, embedding vector(1536),
               created_at)

Refinement vs. the markdown contract: `decisions` are pulled OUT of the Spec
document into their own table. They're append-only, individually addressable
(get_decision), and vector-searchable for the learn->shape flywheel — so they
want to be rows, not nested JSON. The Spec doc holds the *current* contract;
decisions are the log alongside it.

Requires Python 3.11+ (asyncio.timeout), pydantic v2, asyncpg, redis>=4.2 (redis.asyncio).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import asyncpg
from pydantic import BaseModel, ConfigDict, Field
from redis import asyncio as aioredis

from app.embeddings import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def slugify(title: str) -> str:
    """Kebab-case slug from a human title — the initiative id and URL key (0004)."""
    s = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return s or "initiative"


def _vector_literal(vec: list[float]) -> str:
    """pgvector's text input form: '[0.1,0.2,...]'. Bound as a param + cast ::vector,
    so no pgvector python adapter is needed (0005)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _decision_text(d: "Decision") -> str:
    """The semantic content of a resolved decision — the reasoning we want retrievable
    (constraint 5 / D2: decisions are the high-value memory corpus)."""
    parts = [d.question]
    if d.chosen:
        parts.append(f"Chosen: {d.chosen}")
    if d.rationale:
        parts.append(f"Rationale: {d.rationale}")
    return "\n".join(parts)


# ----------------------------------------------------------------------------- models
Provenance = Literal["human", "ai_proposed", "ai_confirmed_by_human"]
ItemStatus = Literal["proposed", "confirmed", "retired"]
Stage = Literal["discover", "shape", "bet", "decompose", "implement", "verify", "learn"]
STAGES: tuple[str, ...] = (
    "discover", "shape", "bet", "decompose", "implement", "verify", "learn",
)


def _is_adjacent_stage(current: str, target: str) -> bool:
    """A legal lifecycle move is exactly one step — forward, or back for rework (0004 c3).
    No skipping; no arbitrary jumps."""
    if current not in STAGES or target not in STAGES:
        return False
    return abs(STAGES.index(current) - STAGES.index(target)) == 1


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


class Memory(BaseModel):
    """An append-only record of a completed (or revisited) initiative (0005): what it
    set out to do vs. what happened, plus learnings. Embedded for cross-initiative
    retrieval. Never edited — a revisit becomes a new row (constraint 4). The embedding
    is a DB column, not a model field (like Decision)."""

    id: str = Field(default_factory=lambda: _id("mem"))
    initiative_id: str
    summary: str
    learnings: str | None = None
    outcome: dict | None = None  # an optional structured snapshot (e.g. per-unit results)
    created_at: str = Field(default_factory=_now)


def _memory_from_row(row: asyncpg.Record) -> Memory:
    return Memory(
        id=row["id"],
        initiative_id=row["initiative_id"],
        summary=row["summary"],
        learnings=row["learnings"],
        outcome=json.loads(row["outcome"]) if row["outcome"] else None,
        created_at=row["created_at"].isoformat(),
    )


class ContextHit(BaseModel):
    """One retrieved memory snippet (0005 u3). Source-attributed so the executor can
    judge whether to trust it (constraint 5): which initiative, which kind of record,
    the text, and a relevance score (1 - cosine distance; higher is closer)."""

    initiative_id: str
    type: Literal["decision", "memory"]
    text: str
    score: float


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


def _initiative_from_row(row: asyncpg.Record) -> Initiative:
    return Initiative(
        id=row["id"], title=row["title"], stage=row["stage"],
        org_id=row["org_id"], owner_id=row["owner_id"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


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


# --- work units: tracked, bounded units decomposed from a spec (0003) --------
# A fixed state machine. A unit is created `proposed`; a human confirms it to `ready`
# before it's workable, and an executor can never confirm its own (no-self-confirm).
# `changes_requested` is a verdict, not a resting status: per 0003 a7 it lands the
# unit back in `in_progress` with feedback — so it is NOT a member of UnitStatus, and
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
        """Move along the fixed state machine, or raise. Every status change goes
        through here — it is the sole legality rule for a unit's lifecycle."""
        if target not in _UNIT_TRANSITIONS.get(self.status, frozenset()):
            raise InvalidTransition(self.id, self.status, target)
        self.status = target
        self.updated_at = _now()
        return self


# ----------------------------------------------------------------------------- errors
class StaleSpecError(Exception):
    def __init__(self, initiative_id: str, expected: int, found: int):
        super().__init__(
            f"spec {initiative_id} changed under you (have v{expected}, db v{found})"
        )
        self.initiative_id, self.expected, self.found = initiative_id, expected, found


class DecisionTimeout(Exception):
    pass


class InvalidTransition(Exception):
    """A work unit was asked to make a status change the state machine forbids."""

    def __init__(self, unit_id: str, current: str, target: str):
        super().__init__(
            f"work unit {unit_id}: {current} -> {target} is not a legal transition"
        )
        self.unit_id, self.current, self.target = unit_id, current, target


class InvalidStageTransition(Exception):
    """An initiative was asked to jump stages — only one step (forward or back) is legal."""

    def __init__(self, initiative_id: str, current: str, target: str):
        super().__init__(
            f"initiative {initiative_id}: {current} -> {target} is not a one-step lifecycle move"
        )
        self.initiative_id, self.current, self.target = initiative_id, current, target


# ----------------------------------------------------------------------------- store
SPEC_CACHE_TTL = 300  # seconds; cache is derived, so a short TTL is just a safety net


class SpecStore:
    def __init__(
        self,
        pg: asyncpg.Pool,
        redis: aioredis.Redis,
        embedder: EmbeddingProvider | None = None,
    ):
        self.pg = pg
        self.redis = redis
        # Pluggable + lazy: the default provider is built on first use so a store
        # never needs an embedding key just to read/write specs (0005 constraint 2).
        self._embedder = embedder
        # fire-and-forget embedding tasks; kept referenced so the loop doesn't GC them.
        self._bg: set[asyncio.Task] = set()

    def _get_embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = get_embedding_provider()
        return self._embedder

    # --- hot read path: Redis read-through -----------------------------------
    async def get_spec(self, initiative_id: str) -> Spec | None:
        key = f"spec:{initiative_id}"
        if cached := await self.redis.get(key):
            return Spec.model_validate_json(cached)

        row = await self.pg.fetchrow(
            "SELECT doc FROM specs WHERE initiative_id = $1", initiative_id
        )
        if row is None:
            return None

        spec = Spec.model_validate_json(row["doc"])
        await self.redis.set(key, spec.model_dump_json(), ex=SPEC_CACHE_TTL)
        return spec

    # --- write path: PG is truth, optimistic version, cache refreshed after ---
    async def save_spec(self, spec: Spec) -> Spec:
        """
        The spec is *living* — a human and an agent can both touch it. The version
        field is the optimistic lock: bump on every confirmed change, reject writes
        built on a stale read so nobody silently clobbers a confirmed constraint.
        """
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchval(
                    "SELECT version FROM specs WHERE initiative_id = $1 FOR UPDATE",
                    spec.initiative_id,
                )
                if current is not None and current != spec.version:
                    raise StaleSpecError(spec.initiative_id, spec.version, current)

                spec.version += 1
                await conn.execute(
                    """
                    INSERT INTO specs (initiative_id, version, doc, updated_at)
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT (initiative_id)
                    DO UPDATE SET version = $2, doc = $3, updated_at = now()
                    """,
                    spec.initiative_id, spec.version, spec.model_dump_json(),
                )

        # cache is derived — refresh it, never trust it as the origin
        await self.redis.set(
            f"spec:{spec.initiative_id}", spec.model_dump_json(), ex=SPEC_CACHE_TTL
        )
        return spec

    # --- initiatives: the parent entity, born with a scaffolded spec (0004) --
    async def create_initiative(
        self, title: str, *, org_id: str | None = None, owner_id: str | None = None
    ) -> Initiative:
        """Create an initiative and scaffold its empty spec in one act (constraint 2):
        the spec is born at version 0, stage=discover, with empty item lists. The id is a
        unique slug derived from the title."""
        slug = await self._unique_slug(slugify(title))
        spec = Spec(initiative_id=slug, title=title, stage="discover")
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO initiatives (id, title, org_id, owner_id, stage, created_at, updated_at)
                       VALUES ($1, $2, $3, $4, 'discover', now(), now())""",
                    slug, title, org_id, owner_id,
                )
                # Scaffold the spec at version 0 directly. A brand-new spec has no prior
                # row to guard, so this doesn't bypass the optimistic lock — the first real
                # edit (via 0002) reads v0 and moves it to v1.
                await conn.execute(
                    """INSERT INTO specs (initiative_id, version, doc, updated_at)
                       VALUES ($1, 0, $2, now())""",
                    slug, spec.model_dump_json(),
                )
        await self.redis.set(f"spec:{slug}", spec.model_dump_json(), ex=SPEC_CACHE_TTL)
        return Initiative(id=slug, title=title, stage="discover", org_id=org_id, owner_id=owner_id)

    async def get_initiative(self, initiative_id: str) -> Initiative | None:
        """The initiative's lifecycle context — surfaced alongside the spec on MCP
        get_spec so an executor grounds itself in stage before acting (D1 / 0004)."""
        row = await self.pg.fetchrow(
            """SELECT id, title, stage, org_id, owner_id, created_at, updated_at
               FROM initiatives WHERE id = $1""",
            initiative_id,
        )
        return _initiative_from_row(row) if row else None

    async def list_initiatives(self) -> list[Initiative]:
        """Every initiative that has a spec — the dashboard's feed (0004 a3). Most recently
        updated first."""
        rows = await self.pg.fetch(
            """SELECT i.id, i.title, i.stage, i.org_id, i.owner_id, i.created_at, i.updated_at
               FROM initiatives i
               JOIN specs s ON s.initiative_id = i.id
               ORDER BY i.updated_at DESC, i.id"""
        )
        return [_initiative_from_row(r) for r in rows]

    async def set_stage(self, initiative_id: str, target: str) -> Initiative:
        """Advance or retreat an initiative by one lifecycle step (0004 a4/a5), keeping the
        spec doc's stage in sync. The stage mirror onto the doc is metadata, not a content
        edit, so it does not bump the spec version (a stage move never 409s a live editor)."""
        init = await self.get_initiative(initiative_id)
        if init is None:
            raise KeyError(initiative_id)
        if not _is_adjacent_stage(init.stage, target):
            raise InvalidStageTransition(initiative_id, init.stage, target)
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE initiatives SET stage = $2, updated_at = now() WHERE id = $1",
                    initiative_id, target,
                )
                await conn.execute(
                    """UPDATE specs SET doc = jsonb_set(doc, '{stage}', to_jsonb($2::text)),
                       updated_at = now() WHERE initiative_id = $1""",
                    initiative_id, target,
                )
        # refresh the derived spec cache from PG truth
        doc = await self.pg.fetchval(
            "SELECT doc FROM specs WHERE initiative_id = $1", initiative_id
        )
        if doc is not None:
            await self.redis.set(f"spec:{initiative_id}", doc, ex=SPEC_CACHE_TTL)
        return await self.get_initiative(initiative_id)

    async def _unique_slug(self, base: str) -> str:
        slug, n = base, 2
        while await self.pg.fetchval("SELECT 1 FROM initiatives WHERE id = $1", slug):
            slug, n = f"{base}-{n}", n + 1
        return slug

    # --- decisions: durable in PG, surfaced + resolved in real time ----------
    async def raise_decision(self, d: Decision, initiative_id: str) -> Decision:
        await self.pg.execute(
            """INSERT INTO decisions (id, initiative_id, payload, status, created_at)
               VALUES ($1, $2, $3, 'open', now())""",
            d.id, initiative_id, d.model_dump_json(),
        )
        # lands on the human's steering rail immediately; Stream survives reconnects
        await self.redis.xadd(
            f"escalations:{initiative_id}", {"decision_id": d.id, "kind": "raised"}
        )
        return d

    async def list_open_decisions(self, initiative_id: str) -> list[Decision]:
        """The rail's read path. Straight from Postgres — decisions have no read
        cache (the escalations Stream is a derived notification log, not a store),
        so this is rebuildable from PG by construction. Oldest first: the longest-
        parked escalation sits at the top of the queue."""
        rows = await self.pg.fetch(
            """SELECT payload FROM decisions
               WHERE initiative_id = $1 AND status = 'open'
               ORDER BY created_at""",
            initiative_id,
        )
        return [Decision.model_validate_json(r["payload"]) for r in rows]

    async def list_decisions(
        self, initiative_id: str, status: str | None = None
    ) -> list[Decision]:
        """All of an initiative's decisions, oldest first, optionally filtered by status.
        The Learn review (0005 a4) reads the resolved set — the chosen calls + rationale
        that explain what happened."""
        if status is None:
            rows = await self.pg.fetch(
                "SELECT payload FROM decisions WHERE initiative_id = $1 ORDER BY created_at",
                initiative_id,
            )
        else:
            rows = await self.pg.fetch(
                """SELECT payload FROM decisions
                   WHERE initiative_id = $1 AND status = $2 ORDER BY created_at""",
                initiative_id, status,
            )
        return [Decision.model_validate_json(r["payload"]) for r in rows]

    async def resolve_decision(
        self, decision_id: str, chosen: str, rationale: str, decided_by: str
    ) -> Decision:
        row = await self.pg.fetchrow(
            "SELECT payload FROM decisions WHERE id = $1", decision_id
        )
        d = Decision.model_validate_json(row["payload"])
        d.chosen, d.rationale, d.decided_by = chosen, rationale, decided_by
        d.status, d.resolved_at = "resolved", _now()

        await self.pg.execute(
            """UPDATE decisions
               SET payload = $2, status = 'resolved', resolved_at = now()
               WHERE id = $1""",
            decision_id, d.model_dump_json(),
        )
        # a decision can park a work unit (blocked_on_decision); resolving it resumes that
        # unit BEFORE we wake the executor, so the awaited call finds it in_progress (a9).
        await self._resume_units_blocked_on(decision_id)
        # wake any agent parked on this exact decision — push, not poll
        await self.redis.publish(f"decision:{decision_id}", d.model_dump_json())
        # embed the resolved reasoning into memory, async + best-effort (0005 constraint 3):
        # it must not block (or break) the resolve. A failure leaves a null embedding for
        # the backfill to pick up.
        self._spawn(self.embed_decision(decision_id))
        return d

    async def wait_for_decision(self, decision_id: str, timeout: float = 600) -> Decision:
        """The agent yields here instead of polling get_decision in a loop."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"decision:{decision_id}")
        try:
            # guard the race: it may have resolved before we subscribed
            row = await self.pg.fetchrow(
                "SELECT payload, status FROM decisions WHERE id = $1", decision_id
            )
            if row and row["status"] == "resolved":
                return Decision.model_validate_json(row["payload"])

            async with asyncio.timeout(timeout):
                async for msg in pubsub.listen():
                    if msg["type"] == "message":
                        return Decision.model_validate_json(msg["data"])
        finally:
            await pubsub.unsubscribe(f"decision:{decision_id}")
        raise DecisionTimeout(decision_id)

    # --- embeddings: decisions become retrievable memory (0005 u1) -----------
    async def embed_decision(self, decision_id: str) -> bool:
        """Embed a decision's resolved reasoning onto its row. Returns False if the
        decision is gone. Synchronous + awaited — the backfill and tests call it
        directly; resolve_decision schedules it in the background instead."""
        row = await self.pg.fetchrow(
            "SELECT payload FROM decisions WHERE id = $1", decision_id
        )
        if row is None:
            return False
        d = Decision.model_validate_json(row["payload"])
        [vec] = await self._get_embedder().embed([_decision_text(d)])
        await self.pg.execute(
            "UPDATE decisions SET embedding = $2::vector WHERE id = $1",
            decision_id, _vector_literal(vec),
        )
        return True

    def _spawn(self, coro) -> None:
        """Run an embed in the background, kept referenced so the loop won't GC it.
        Best-effort: a missing key or API hiccup is logged, never raised at the caller
        (0005 constraint 3 — resolving / completing must not block or break)."""
        task = asyncio.create_task(self._safe(coro))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    @staticmethod
    async def _safe(coro) -> None:
        try:
            await coro
        except Exception:
            logger.warning("background embed task failed", exc_info=True)

    async def _drain(self) -> None:
        """Await any in-flight background embeds — for graceful shutdown and tests."""
        if self._bg:
            await asyncio.gather(*self._bg, return_exceptions=True)

    # --- memory: the append-only record the Learn stage writes (0005 u2) -----
    async def create_memory(
        self,
        initiative_id: str,
        summary: str,
        learnings: str | None = None,
        outcome: dict | None = None,
    ) -> Memory:
        """Write a completed initiative's memory row and embed it async (constraint 3:
        completing Learn must not block). Append-only — every call is a new row."""
        mem = Memory(
            initiative_id=initiative_id, summary=summary, learnings=learnings, outcome=outcome
        )
        await self.pg.execute(
            """INSERT INTO memory (id, initiative_id, summary, learnings, outcome, created_at)
               VALUES ($1, $2, $3, $4, $5, now())""",
            mem.id, initiative_id, summary, learnings,
            json.dumps(outcome) if outcome is not None else None,
        )
        self._spawn(self.embed_memory(mem.id))
        return mem

    async def embed_memory(self, memory_id: str) -> bool:
        row = await self.pg.fetchrow(
            "SELECT summary, learnings FROM memory WHERE id = $1", memory_id
        )
        if row is None:
            return False
        text = row["summary"] + (f"\n\nLearnings: {row['learnings']}" if row["learnings"] else "")
        [vec] = await self._get_embedder().embed([text])
        await self.pg.execute(
            "UPDATE memory SET embedding = $2::vector WHERE id = $1",
            memory_id, _vector_literal(vec),
        )
        return True

    async def list_memory(self, initiative_id: str) -> list[Memory]:
        """An initiative's memory rows, newest first."""
        rows = await self.pg.fetch(
            """SELECT id, initiative_id, summary, learnings, outcome, created_at
               FROM memory WHERE initiative_id = $1 ORDER BY created_at DESC""",
            initiative_id,
        )
        return [_memory_from_row(r) for r in rows]

    async def get_context(self, query: str, limit: int = 8) -> list[ContextHit]:
        """Similarity search over the memory corpus — resolved decisions + completed-
        initiative memory (D2 scope) — across ALL initiatives, so an executor shaping or
        building the next feature retrieves relevant prior patterns (0005 a6/a7/a8).
        Ranked by cosine similarity; rows without an embedding are skipped."""
        if not query.strip():
            return []
        [qvec] = await self._get_embedder().embed([query])
        rows = await self.pg.fetch(
            """
            SELECT type, initiative_id, txt, dist FROM (
                SELECT 'decision' AS type, initiative_id,
                       concat_ws(' — ', payload->>'question',
                           NULLIF('Chosen: ' || coalesce(payload->>'chosen', ''), 'Chosen: '),
                           NULLIF('Rationale: ' || coalesce(payload->>'rationale', ''), 'Rationale: ')
                       ) AS txt,
                       embedding <=> $1::vector AS dist
                  FROM decisions WHERE embedding IS NOT NULL
                UNION ALL
                SELECT 'memory' AS type, initiative_id,
                       concat_ws(' — ', summary,
                           NULLIF('Learnings: ' || coalesce(learnings, ''), 'Learnings: ')
                       ) AS txt,
                       embedding <=> $1::vector AS dist
                  FROM memory WHERE embedding IS NOT NULL
            ) q
            ORDER BY dist
            LIMIT $2
            """,
            _vector_literal(qvec), limit,
        )
        return [
            ContextHit(
                initiative_id=r["initiative_id"],
                type=r["type"],
                text=r["txt"],
                score=round(1.0 - float(r["dist"]), 4),
            )
            for r in rows
        ]

    # --- work units: durable rows in their own table (0003) ------------------
    async def create_unit(self, unit: WorkUnit) -> WorkUnit:
        await self.pg.execute(
            """INSERT INTO work_units (id, spec_id, payload, status, created_at, updated_at)
               VALUES ($1, $2, $3, $4, now(), now())""",
            unit.id, unit.spec_id, unit.model_dump_json(), unit.status,
        )
        return unit

    async def get_unit(self, unit_id: str) -> WorkUnit | None:
        row = await self.pg.fetchrow(
            "SELECT payload FROM work_units WHERE id = $1", unit_id
        )
        return WorkUnit.model_validate_json(row["payload"]) if row else None

    async def save_unit(self, unit: WorkUnit) -> WorkUnit:
        """Persist a unit after a transition. payload is the truth; status is a
        promoted column so list_units can filter without parsing JSON."""
        unit.updated_at = _now()
        await self.pg.execute(
            """UPDATE work_units SET payload = $2, status = $3, updated_at = now()
               WHERE id = $1""",
            unit.id, unit.model_dump_json(), unit.status,
        )
        return unit

    async def list_units(self, spec_id: str, status: str | None = None) -> list[WorkUnit]:
        """The executor's read path (a3). Oldest first; optionally filtered by status,
        served off the promoted status column so no JSON parsing is needed to filter."""
        if status is None:
            rows = await self.pg.fetch(
                "SELECT payload FROM work_units WHERE spec_id = $1 ORDER BY created_at",
                spec_id,
            )
        else:
            rows = await self.pg.fetch(
                """SELECT payload FROM work_units
                   WHERE spec_id = $1 AND status = $2 ORDER BY created_at""",
                spec_id, status,
            )
        return [WorkUnit.model_validate_json(r["payload"]) for r in rows]

    async def claim_unit(self, unit_id: str) -> WorkUnit:
        """The executor claims a confirmed unit to start building (ready -> in_progress).
        Only a confirmed (ready) unit can be claimed."""
        unit = await self._require_unit(unit_id)
        unit.transition("in_progress")
        return await self.save_unit(unit)

    async def report_progress(self, unit_id: str, note: str) -> WorkUnit:
        unit = await self._require_unit(unit_id)
        unit.progress_note = note
        return await self.save_unit(unit)

    async def submit_for_verification(self, unit_id: str, submission: Submission) -> WorkUnit:
        """Hand a unit back for judgment: in_progress -> in_verification. The executor must
        map its output to at least one acceptance criterion (constraint 4)."""
        if not submission.criteria_results:
            raise ValueError("submit_for_verification requires at least one criterion result")
        unit = await self._require_unit(unit_id)
        unit.submission = submission
        unit.transition("in_verification")  # raises InvalidTransition unless in_progress
        return await self.save_unit(unit)

    async def get_verification(self, unit_id: str) -> Verdict | None:
        """The verdict a human gave, or None if not yet judged. Read-only — there is no
        path here that sets a verdict (no self-approval)."""
        return (await self._require_unit(unit_id)).verdict

    # --- human verdict + unit/decision linking (u3): humans confirm and judge ---------
    async def confirm_unit(self, unit_id: str) -> WorkUnit:
        """A human confirms a proposed unit -> ready — the only path to workable (a4).
        Raises InvalidTransition unless the unit is proposed."""
        unit = await self._require_unit(unit_id)
        unit.transition("ready")
        return await self.save_unit(unit)

    async def record_verdict(
        self, unit_id: str, verdict: str, feedback: str, decided_by: str
    ) -> WorkUnit:
        """A human judges a submitted unit (a7): approved -> done; changes_requested ->
        in_progress with feedback attached. Legal only from in_verification."""
        unit = await self._require_unit(unit_id)
        unit.verdict = Verdict(verdict=verdict, feedback=feedback, decided_by=decided_by)
        unit.transition("done" if verdict == "approved" else "in_progress")
        return await self.save_unit(unit)

    async def block_on_decision(self, unit_id: str, decision_id: str) -> WorkUnit:
        """Park a unit on a decision (in_progress -> blocked_on_decision). The matching
        resume happens automatically when the decision resolves."""
        unit = await self._require_unit(unit_id)
        unit.blocked_on = decision_id
        unit.transition("blocked_on_decision")
        return await self.save_unit(unit)

    async def _resume_units_blocked_on(self, decision_id: str) -> None:
        rows = await self.pg.fetch(
            """SELECT payload FROM work_units
               WHERE status = 'blocked_on_decision' AND payload->>'blocked_on' = $1""",
            decision_id,
        )
        for r in rows:
            unit = WorkUnit.model_validate_json(r["payload"])
            unit.blocked_on = None
            unit.transition("in_progress")
            await self.save_unit(unit)

    async def _require_unit(self, unit_id: str) -> WorkUnit:
        unit = await self.get_unit(unit_id)
        if unit is None:
            raise KeyError(unit_id)
        return unit

    # --- ephemeral agent state: Redis-native, never persisted ----------------
    async def heartbeat(self, unit_id: str, note: str) -> None:
        # drives the live "agents at work" strip; expires on its own, by design
        await self.redis.set(f"unit:{unit_id}:beat", note, ex=30)


# ----------------------------------------------------------------------------- wiring
# FastAPI lifespan — one pool, one redis client, shared:
#
#   from contextlib import asynccontextmanager
#
#   @asynccontextmanager
#   async def lifespan(app):
#       app.state.pg = await asyncpg.create_pool(DSN, min_size=2, max_size=10)
#       app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
#       yield
#       await app.state.pg.close()
#       await app.state.redis.aclose()
#
#   def store(req: Request) -> SpecStore:
#       return SpecStore(req.app.state.pg, req.app.state.redis)
#
#   @app.get("/specs/{initiative_id}")
#   async def read_spec(initiative_id: str, s: SpecStore = Depends(store)) -> Spec:
#       spec = await s.get_spec(initiative_id)
#       if spec is None:
#           raise HTTPException(404)
#       return spec
