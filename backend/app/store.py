"""SpecStore — the async data-access layer (repository).

Architecture:
  Postgres = source of truth (durable). The spec is one JSONB document per initiative.
  Redis    = derived hot state: read-through cache + real-time coordination. Always
             rebuildable from Postgres, never the other way round.

Relational surface (see migrations/):
  initiatives (id pk, org_id, owner_id, appetite, stage, title, created_at, updated_at)
  specs       (initiative_id pk, version int, doc jsonb, updated_at)
  decisions   (id pk, initiative_id, payload jsonb, status, embedding vector(1536), ...)
  memory      (id pk, initiative_id, summary, learnings, outcome jsonb, embedding, ...)
  work_units  (id pk, spec_id, payload jsonb, status, created_at, updated_at)

Decisions live in their own table (not the spec doc): append-only, individually
addressable, and vector-searchable for the learn->shape flywheel. The domain models
live in app.models; the framework-agnostic errors in app.exceptions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

import asyncpg
from redis import asyncio as aioredis

from app.exceptions import (
    DecisionTimeout,
    InvalidStageTransition,
    NotFoundError,
    StaleSpecError,
)
from app.models import (
    ContextHit,
    Decision,
    Guidance,
    Initiative,
    Memory,
    Message,
    MessageRole,
    Project,
    ProjectContext,
    SiblingSummary,
    Spec,
    Submission,
    Verdict,
    WorkUnit,
    _now,
    is_adjacent_stage,
    slug_prefix,
    slugify,
)
from app.providers.embeddings import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- helpers
def _vector_literal(vec: list[float]) -> str:
    """pgvector's text input form: '[0.1,0.2,...]'. Bound as a param + cast ::vector, so
    no pgvector python adapter is needed (0005)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _decision_text(d: Decision) -> str:
    """The semantic content of a resolved decision — the reasoning we want retrievable
    (constraint 5 / D2: decisions are the high-value memory corpus)."""
    parts = [d.question]
    if d.chosen:
        parts.append(f"Chosen: {d.chosen}")
    if d.rationale:
        parts.append(f"Rationale: {d.rationale}")
    return "\n".join(parts)


def _initiative_from_row(row: asyncpg.Record) -> Initiative:
    return Initiative(
        id=row["id"], title=row["title"], stage=row["stage"],
        project_id=row["project_id"],
        org_id=row["org_id"], owner_id=row["owner_id"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


def _project_from_row(row: asyncpg.Record) -> Project:
    return Project(
        id=row["id"], name=row["name"], intent=row["intent"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


def _decision_summary(d: Decision) -> str:
    """A one-line summary of a resolved decision for a sibling's compact summary (0010 u3)."""
    return f"{d.question} — Chosen: {d.chosen}" if d.chosen else d.question


def _sibling_summary(
    row: asyncpg.Record, latest_decisions: dict[str, str], max_constraints: int
) -> SiblingSummary:
    spec = Spec.model_validate_json(row["doc"])
    confirmed = spec.confirmed_constraints()
    return SiblingSummary(
        initiative_id=row["id"],
        title=spec.title,
        stage=row["stage"],
        constraint_count=len(confirmed),
        constraints=[c.text for c in confirmed[:max_constraints]],
        latest_decision=latest_decisions.get(row["id"]),
    )


def _memory_from_row(row: asyncpg.Record) -> Memory:
    return Memory(
        id=row["id"],
        initiative_id=row["initiative_id"],
        summary=row["summary"],
        learnings=row["learnings"],
        outcome=json.loads(row["outcome"]) if row["outcome"] else None,
        created_at=row["created_at"].isoformat(),
    )


def _message_from_row(row: asyncpg.Record) -> Message:
    return Message(
        id=row["id"],
        initiative_id=row["initiative_id"],
        project_id=row["project_id"],
        role=row["role"],
        content=row["content"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        created_at=row["created_at"].isoformat(),
    )


# ----------------------------------------------------------------------------- store
SPEC_CACHE_TTL = 300  # seconds; cache is derived, so a short TTL is just a safety net
MESSAGE_WINDOW = 30   # recent messages an Advisor context assembly includes (0009 discretion)
GUIDANCE_CACHE_TTL = 300  # seconds; a unit briefing is regenerated on demand after it lapses
# Project context is rendered into every Advisor turn for a project initiative, so it must
# stay compact (0010 constraint 3): cap how many siblings, and how many constraint headlines
# per sibling, the summaries carry. The Advisor retrieves specifics on demand via get_context.
PROJECT_SIBLING_LIMIT = 12
SIBLING_CONSTRAINT_HEADLINES = 3


class SpecStore:
    def __init__(
        self,
        pg: asyncpg.Pool,
        redis: aioredis.Redis,
        embedder: EmbeddingProvider | None = None,
    ):
        self.pg = pg
        self.redis = redis
        # Pluggable + lazy: the default provider is built on first use so a store never
        # needs an embedding key just to read/write specs (0005 constraint 2).
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
        The spec is *living* — a human and an agent can both touch it. The version field
        is the optimistic lock: bump on every confirmed change, reject writes built on a
        stale read so nobody silently clobbers a confirmed constraint.
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
        self,
        title: str,
        project_id: str,
        *,
        org_id: str | None = None,
        owner_id: str | None = None,
    ) -> Initiative:
        """Create an initiative under a project and scaffold its empty spec in one act
        (constraint 2): the spec is born at version 0, stage=discover, with empty item lists.
        The id is a unique slug derived from the title. Every initiative belongs to a project —
        `project_id` is required and must exist (no orphan specs)."""
        if await self.get_project(project_id) is None:
            raise NotFoundError(f"no project {project_id}")
        slug = await self._unique_slug(f"{slug_prefix()}-{slugify(title)}")
        spec = Spec(initiative_id=slug, title=title, stage="discover")
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO initiatives
                           (id, title, project_id, org_id, owner_id, stage, created_at, updated_at)
                       VALUES ($1, $2, $3, $4, $5, 'discover', now(), now())""",
                    slug, title, project_id, org_id, owner_id,
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
        return Initiative(
            id=slug, title=title, stage="discover",
            project_id=project_id, org_id=org_id, owner_id=owner_id,
        )

    async def get_initiative(self, initiative_id: str) -> Initiative | None:
        """The initiative's lifecycle context — surfaced alongside the spec on MCP get_spec
        so an executor grounds itself in stage before acting (D1 / 0004)."""
        row = await self.pg.fetchrow(
            """SELECT id, title, stage, project_id, org_id, owner_id, created_at, updated_at
               FROM initiatives WHERE id = $1""",
            initiative_id,
        )
        return _initiative_from_row(row) if row else None

    async def list_initiatives(self) -> list[Initiative]:
        """Every initiative that has a spec — the dashboard's feed (0004 a3). Most recently
        updated first."""
        rows = await self.pg.fetch(
            """SELECT i.id, i.title, i.stage, i.project_id, i.org_id, i.owner_id,
                      i.created_at, i.updated_at
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
            raise NotFoundError(f"no initiative {initiative_id}")
        if not is_adjacent_stage(init.stage, target):
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
        updated = await self.get_initiative(initiative_id)
        assert updated is not None  # it exists — we just updated it in the transaction above
        return updated

    async def _unique_slug(self, base: str) -> str:
        slug, n = base, 2
        while await self.pg.fetchval("SELECT 1 FROM initiatives WHERE id = $1", slug):
            slug, n = f"{base}-{n}", n + 1
        return slug

    # --- projects: group initiatives under a strategic intent (0010 u1) ------
    async def create_project(self, name: str, intent: str = "") -> Project:
        """Create a project with a unique slug: a short random prefix + the name-derived part
        (constraint 1), so distinct projects never collide."""
        base = f"{slug_prefix()}-{slugify(name)}"
        slug, n = base, 2
        while await self.pg.fetchval("SELECT 1 FROM projects WHERE id = $1", slug):
            slug, n = f"{base}-{n}", n + 1
        proj = Project(id=slug, name=name, intent=intent)
        await self.pg.execute(
            """INSERT INTO projects (id, name, intent, created_at, updated_at)
               VALUES ($1, $2, $3, now(), now())""",
            proj.id, proj.name, proj.intent,
        )
        return proj

    async def get_project(self, project_id: str) -> Project | None:
        row = await self.pg.fetchrow(
            "SELECT id, name, intent, created_at, updated_at FROM projects WHERE id = $1",
            project_id,
        )
        return _project_from_row(row) if row else None

    async def list_projects(self) -> list[Project]:
        """Every project, newest first — the level above the dashboard (0010 a2)."""
        rows = await self.pg.fetch(
            """SELECT id, name, intent, created_at, updated_at
               FROM projects ORDER BY created_at DESC, id"""
        )
        return [_project_from_row(r) for r in rows]

    async def list_project_initiatives(self, project_id: str) -> list[Initiative]:
        """The initiatives grouped under a project (0010 a2/a7), most recently updated first."""
        rows = await self.pg.fetch(
            """SELECT i.id, i.title, i.stage, i.project_id, i.org_id, i.owner_id,
                      i.created_at, i.updated_at
               FROM initiatives i
               JOIN specs s ON s.initiative_id = i.id
               WHERE i.project_id = $1
               ORDER BY i.updated_at DESC, i.id""",
            project_id,
        )
        return [_initiative_from_row(r) for r in rows]

    async def get_project_context(
        self,
        project_id: str,
        *,
        exclude: str | None = None,
        sibling_limit: int = PROJECT_SIBLING_LIMIT,
        max_constraints: int = SIBLING_CONSTRAINT_HEADLINES,
    ) -> ProjectContext | None:
        """Compact project context for an Advisor turn (0010 constraint 2/3): the project's
        strategic intent + token-conscious summaries of its sibling initiatives (title, stage,
        headline confirmed constraints + count, most recent resolved decision). `exclude` drops
        the initiative in focus. Returns None if the project is gone. NOT full specs — the
        Advisor retrieves specifics on demand via project-scoped get_context (u4)."""
        proj = await self.get_project(project_id)
        if proj is None:
            return None
        rows = await self.pg.fetch(
            """SELECT i.id, i.stage, s.doc
               FROM initiatives i
               JOIN specs s ON s.initiative_id = i.id
               WHERE i.project_id = $1 AND ($2::text IS NULL OR i.id <> $2)
               ORDER BY i.updated_at DESC, i.id
               LIMIT $3""",
            project_id, exclude, sibling_limit,
        )
        # the most recent resolved decision per sibling, in one pass (DISTINCT ON)
        dec_rows = await self.pg.fetch(
            """SELECT DISTINCT ON (d.initiative_id) d.initiative_id, d.payload
               FROM decisions d
               JOIN initiatives i ON i.id = d.initiative_id
               WHERE i.project_id = $1 AND ($2::text IS NULL OR i.id <> $2)
                 AND d.status = 'resolved'
               ORDER BY d.initiative_id, d.resolved_at DESC NULLS LAST""",
            project_id, exclude,
        )
        latest = {
            r["initiative_id"]: _decision_summary(Decision.model_validate_json(r["payload"]))
            for r in dec_rows
        }
        siblings = [_sibling_summary(r, latest, max_constraints) for r in rows]
        return ProjectContext(
            project_id=proj.id, name=proj.name, intent=proj.intent, siblings=siblings
        )

    async def count_open_decisions(self, project_id: str) -> int:
        """Open escalations across every initiative in a project — a whole-project aggregate
        for the dashboard (0010 a2)."""
        return await self.pg.fetchval(
            """SELECT count(*) FROM decisions d
               JOIN initiatives i ON i.id = d.initiative_id
               WHERE i.project_id = $1 AND d.status = 'open'""",
            project_id,
        )

    async def assign_initiative_to_project(
        self, initiative_id: str, project_id: str
    ) -> Initiative:
        """Move an initiative to a (different) project. Both must exist. There is no detach —
        every initiative belongs to a project (no orphan specs)."""
        if await self.get_initiative(initiative_id) is None:
            raise NotFoundError(f"no initiative {initiative_id}")
        if await self.get_project(project_id) is None:
            raise NotFoundError(f"no project {project_id}")
        await self.pg.execute(
            "UPDATE initiatives SET project_id = $2, updated_at = now() WHERE id = $1",
            initiative_id, project_id,
        )
        updated = await self.get_initiative(initiative_id)
        assert updated is not None  # it exists — we just updated it
        return updated

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

    async def get_decision(self, decision_id: str) -> Decision | None:
        row = await self.pg.fetchrow(
            "SELECT payload FROM decisions WHERE id = $1", decision_id
        )
        return Decision.model_validate_json(row["payload"]) if row else None

    async def list_open_decisions(self, initiative_id: str) -> list[Decision]:
        """The rail's read path. Straight from Postgres — decisions have no read cache (the
        escalations Stream is a derived notification log, not a store), so this is
        rebuildable from PG by construction. Oldest first: the longest-parked escalation
        sits at the top of the queue."""
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
        # it must not block (or break) the resolve. A failure leaves a null embedding for the
        # backfill to pick up.
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
        """Embed a decision's resolved reasoning onto its row. Returns False if the decision
        is gone. Synchronous + awaited — the backfill and tests call it directly;
        resolve_decision schedules it in the background instead."""
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

    async def get_context(
        self, query: str, limit: int = 8, *, project_id: str | None = None
    ) -> list[ContextHit]:
        """Similarity search over the memory corpus — resolved decisions + completed-
        initiative memory (D2 scope) — so an executor shaping or building the next feature
        retrieves relevant prior patterns (0005 a6/a7/a8). Ranked by cosine similarity; rows
        without an embedding are skipped.

        0010 constraint 4: when `project_id` is given (the calling initiative belongs to a
        project), search WITHIN the project first; only if those are insufficient to fill
        `limit` does it fall back to the rest of the corpus (outside the project). Each hit is
        tagged with its scope (project / global) and its source initiative. With no project_id
        it's the original global search (scope stays None) — standalone initiatives unaffected."""
        if not query.strip():
            return []
        [qvec] = await self._get_embedder().embed([query])
        if project_id is None:
            return await self._context_search(qvec, limit)
        project_hits = await self._context_search(qvec, limit, project_id=project_id)
        for h in project_hits:
            h.scope = "project"
        if len(project_hits) >= limit:
            return project_hits
        # project results are insufficient — fill the rest from OUTSIDE the project (a4)
        fallback = await self._context_search(
            qvec, limit - len(project_hits), exclude_project=project_id
        )
        for h in fallback:
            h.scope = "global"
        return project_hits + fallback

    async def _context_search(
        self,
        qvec: list[float],
        limit: int,
        *,
        project_id: str | None = None,
        exclude_project: str | None = None,
    ) -> list[ContextHit]:
        """One ranked pass over the corpus. `project_id` restricts to a project's initiatives;
        `exclude_project` restricts to everything outside one (the global fallback). The join
        to initiatives never drops rows — decisions/memory cascade-delete with their
        initiative, so every embedded row has a live parent."""
        rows = await self.pg.fetch(
            """
            SELECT q.type, q.initiative_id, q.txt, q.dist FROM (
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
            JOIN initiatives i ON i.id = q.initiative_id
            WHERE ($2::text IS NULL OR i.project_id = $2)
              AND ($3::text IS NULL OR i.project_id IS DISTINCT FROM $3)
            ORDER BY q.dist
            LIMIT $4
            """,
            _vector_literal(qvec), project_id, exclude_project, limit,
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

    # --- conversation: the rail's persisted history (0009 u1) ----------------
    async def append_message(
        self,
        initiative_id: str,
        role: MessageRole,
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        """Append one message row (constraint 1: individual rows). created_at is taken from
        the column default so the DB clock is the single source of truth for the timestamp."""
        msg = Message(initiative_id=initiative_id, role=role, content=content, metadata=metadata or {})
        row = await self.pg.fetchrow(
            """INSERT INTO messages (id, initiative_id, role, content, metadata)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id, initiative_id, project_id, role, content, metadata, created_at""",
            msg.id, initiative_id, role, content, json.dumps(msg.metadata),
        )
        return _message_from_row(row)

    async def list_messages(
        self, initiative_id: str, limit: int | None = None
    ) -> list[Message]:
        """An initiative's conversation, oldest-first. With no limit the rail gets the full
        history (a4); with a limit it gets the most recent `limit` (still oldest-first) — the
        Advisor's windowed context (constraint 1)."""
        if limit is None:
            rows = await self.pg.fetch(
                """SELECT id, initiative_id, project_id, role, content, metadata, created_at
                   FROM messages WHERE initiative_id = $1 ORDER BY seq""",
                initiative_id,
            )
        else:
            rows = await self.pg.fetch(
                """SELECT id, initiative_id, project_id, role, content, metadata, created_at FROM (
                       SELECT * FROM messages WHERE initiative_id = $1
                       ORDER BY seq DESC LIMIT $2
                   ) recent ORDER BY seq""",
                initiative_id, limit,
            )
        return [_message_from_row(r) for r in rows]

    # --- project conversation: the project-level rail's history (0010 u5) ----
    async def append_project_message(
        self,
        project_id: str,
        role: MessageRole,
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        """Append one project-owned message row (initiative_id NULL, project_id set). The same
        table as the initiative rail — one Message abstraction, two owners (u5)."""
        msg = Message(project_id=project_id, role=role, content=content, metadata=metadata or {})
        row = await self.pg.fetchrow(
            """INSERT INTO messages (id, project_id, role, content, metadata)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id, initiative_id, project_id, role, content, metadata, created_at""",
            msg.id, project_id, role, content, json.dumps(msg.metadata),
        )
        return _message_from_row(row)

    async def list_project_messages(
        self, project_id: str, limit: int | None = None
    ) -> list[Message]:
        """A project's conversation, oldest-first; with a limit, the most recent `limit` (still
        oldest-first) — the project Advisor's windowed context."""
        if limit is None:
            rows = await self.pg.fetch(
                """SELECT id, initiative_id, project_id, role, content, metadata, created_at
                   FROM messages WHERE project_id = $1 ORDER BY seq""",
                project_id,
            )
        else:
            rows = await self.pg.fetch(
                """SELECT id, initiative_id, project_id, role, content, metadata, created_at FROM (
                       SELECT * FROM messages WHERE project_id = $1
                       ORDER BY seq DESC LIMIT $2
                   ) recent ORDER BY seq""",
                project_id, limit,
            )
        return [_message_from_row(r) for r in rows]

    # --- guidance cache: a derived, short-lived unit briefing (0009 u4) ------
    def _guidance_key(self, unit_id: str, spec_version: int) -> str:
        # spec_version in the key = automatic invalidation: a spec edit bumps the version, so
        # the stale briefing's key is simply never read again (it expires on its own).
        return f"guidance:{unit_id}:{spec_version}"

    async def read_guidance_cache(self, unit_id: str, spec_version: int) -> Guidance | None:
        cached = await self.redis.get(self._guidance_key(unit_id, spec_version))
        return Guidance.model_validate_json(cached) if cached else None

    async def write_guidance_cache(self, guidance: Guidance) -> None:
        await self.redis.set(
            self._guidance_key(guidance.unit_id, guidance.spec_version),
            guidance.model_dump_json(),
            ex=GUIDANCE_CACHE_TTL,
        )

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
        """Persist a unit after a transition. payload is the truth; status is a promoted
        column so list_units can filter without parsing JSON."""
        unit.updated_at = _now()
        await self.pg.execute(
            """UPDATE work_units SET payload = $2, status = $3, updated_at = now()
               WHERE id = $1""",
            unit.id, unit.model_dump_json(), unit.status,
        )
        return unit

    async def list_units(self, spec_id: str, status: str | None = None) -> list[WorkUnit]:
        """The executor's read path (a3). Oldest first; optionally filtered by status, served
        off the promoted status column so no JSON parsing is needed to filter."""
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
        """The verdict a human gave, or None if not yet judged. Read-only — there is no path
        here that sets a verdict (no self-approval)."""
        return (await self._require_unit(unit_id)).verdict

    # --- human verdict + unit/decision linking (u3): humans confirm and judge ---------
    async def confirm_unit(self, unit_id: str) -> WorkUnit:
        """A human confirms a proposed unit -> ready — the only path to workable (a4). Raises
        InvalidTransition unless the unit is proposed."""
        unit = await self._require_unit(unit_id)
        unit.transition("ready")
        return await self.save_unit(unit)

    async def record_verdict(
        self,
        unit_id: str,
        verdict: Literal["approved", "changes_requested"],
        feedback: str,
        decided_by: str,
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
            raise NotFoundError(f"no work unit {unit_id}")
        return unit

    # --- ephemeral agent state: Redis-native, never persisted ----------------
    async def heartbeat(self, unit_id: str, note: str) -> None:
        # drives the live "agents at work" strip; expires on its own, by design
        await self.redis.set(f"unit:{unit_id}:beat", note, ex=30)
