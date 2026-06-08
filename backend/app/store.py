"""SpecStore — the async data-access layer (repository).

Architecture:
  Postgres = source of truth (durable). The spec is one JSONB document per initiative.
  Redis    = real-time coordination only (decision pub/sub + escalation stream). Always
             rebuildable from Postgres, never the other way round.

Relational surface (see migrations/):
  initiatives   (id pk, org_id, owner_id, appetite, state, title, created_at, updated_at)
  specs         (initiative_id pk, version int, doc jsonb, updated_at)
  decisions     (id pk, initiative_id, payload jsonb, status, embedding vector(1536), ...)
  memory        (id pk, initiative_id, summary, learnings, outcome jsonb, embedding, last_verified_at, ...)
  drift_reports (id pk, memory_id fk, initiative_id, current_evidence, is_obsolete, status, ...)

Decisions live in their own table (not the spec doc): append-only, individually
addressable, and vector-searchable for the learn->shape flywheel. The domain models
live in app.models; the framework-agnostic errors in app.exceptions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Callable, Coroutine

import asyncpg
from redis import asyncio as aioredis

from app.exceptions import (
    DecisionTimeout,
    NotFoundError,
    StaleSpecError,
    ValidationError,
)
from app.models import (
    ContextHit,
    Decision,
    DriftReport,
    DriftReportStatus,
    Heuristic,
    Initiative,
    InitiativeAttention,
    InitiativeType,
    Memory,
    Observation,
    Project,
    ProjectContext,
    SiblingSummary,
    Spec,
    _now,
    derive_prefix,
    slugify,
)
from app.providers.embeddings import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- helpers
def _vector_literal(vec: list[float]) -> str:
    """pgvector's text input form: '[0.1,0.2,...]'. Bound as a param + cast ::vector, so
    no pgvector python adapter is needed (0005)."""
    return "[" + ",".join(repr(x) for x in vec) + "]"


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
        id=row["id"], title=row["title"], state=row["state"],
        project_id=row["project_id"], seq=row["seq"],
        initiative_type=row["initiative_type"],
        org_id=row["org_id"], owner_id=row["owner_id"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


def _project_from_row(row: asyncpg.Record) -> Project:
    return Project(
        id=row["id"], name=row["name"], prefix=row["prefix"], intent=row["intent"],
        onboarding_dismissed=row["onboarding_dismissed"],
        archived=row["archived_at"] is not None,
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
        seq=row["seq"],
        title=spec.title,
        state=row["state"],
        constraint_count=len(confirmed),
        constraints=[c.text for c in confirmed[:max_constraints]],
        latest_decision=latest_decisions.get(row["id"]),
    )


def _memory_from_row(row: asyncpg.Record) -> Memory:
    lv = row["last_verified_at"]
    return Memory(
        id=row["id"],
        initiative_id=row["initiative_id"],
        summary=row["summary"],
        learnings=row["learnings"],
        outcome=json.loads(row["outcome"]) if row["outcome"] else None,
        initiative_type=row["initiative_type"],
        created_at=row["created_at"].isoformat(),
        last_verified_at=lv.isoformat() if lv is not None else None,
    )


def _drift_report_from_row(row: asyncpg.Record) -> DriftReport:
    ra = row["resolved_at"]
    quality_raw = row["quality"]
    return DriftReport(
        id=row["id"],
        memory_id=row["memory_id"],
        initiative_id=row["initiative_id"],
        current_evidence=row["current_evidence"],
        is_obsolete=row["is_obsolete"],
        status=row["status"],
        resolution_note=row["resolution_note"],
        quality=json.loads(quality_raw) if quality_raw else None,
        created_at=row["created_at"].isoformat(),
        resolved_at=ra.isoformat() if ra is not None else None,
    )


def _heuristic_from_row(row: asyncpg.Record) -> Heuristic:
    return Heuristic(
        id=row["id"],
        initiative_id=row["initiative_id"],
        project_id=row["project_id"],
        rule=row["rule"],
        tags=list(row["tags"] or []),
        superseded_by=row["superseded_by"],
        replaces=row["replaces"],
        created_at=row["created_at"].isoformat(),
    )


def _observation_from_row(row: asyncpg.Record) -> Observation:
    return Observation(
        id=row["id"],
        project_id=row["project_id"],
        content=row["content"],
        status=row["status"],
        resolved_initiative_id=row["resolved_initiative_id"],
        created_at=row["created_at"].isoformat(),
    )


# ----------------------------------------------------------------------------- store
# Conversations live in the browser now (spec uvama): the frontend windows its own history and
# sends a slice with each Advisor call. This is the backend's defensive cap on how many of those
# turns it will fold into a prompt — a safety net against a client sending an unbounded slice.
MESSAGE_WINDOW = 30
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

    async def get_spec(self, initiative_id: str) -> Spec | None:
        row = await self.pg.fetchrow(
            "SELECT doc FROM specs WHERE initiative_id = $1", initiative_id
        )
        if row is None:
            return None
        return Spec.model_validate_json(row["doc"])

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
        return spec

    # --- initiatives: the parent entity, born with a scaffolded spec (0004) --
    async def create_initiative(
        self,
        title: str,
        project_id: str,
        *,
        initiative_type: InitiativeType = "engineering",
        org_id: str | None = None,
        owner_id: str | None = None,
    ) -> Initiative:
        """Create an initiative under a project and scaffold its empty spec in one act
        (constraint 2): the spec is born at version 0, state=draft (0011), with empty item lists.
        The id is {project.prefix}-{seq} (e.g. BD-1), assigned server-side — the client never
        supplies it. Every initiative belongs to a project — `project_id` is required and must
        exist (no orphan specs). BD-15: `initiative_type` persists the creation-time choice
        (engineering / research) and is mirrored into the spec JSONB so both read paths expose it."""
        if await self.get_project(project_id) is None:
            raise NotFoundError(f"no project {project_id}")
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                # Lock the project row to serialize seq assignment across concurrent creations
                # and read the prefix in one query (avhle u1).
                prefix: str = await conn.fetchval(
                    "SELECT prefix FROM projects WHERE id = $1 FOR UPDATE", project_id
                )
                seq: int = await conn.fetchval(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM initiatives WHERE project_id = $1",
                    project_id,
                )
                new_id = f"{prefix}-{seq}"
                spec = Spec(
                    initiative_id=new_id, title=title, state="draft",
                    initiative_type=initiative_type,
                )
                await conn.execute(
                    """INSERT INTO initiatives
                           (id, title, project_id, seq, org_id, owner_id,
                            state, initiative_type, created_at, updated_at)
                       VALUES ($1, $2, $3, $4, $5, $6, 'draft', $7, now(), now())""",
                    new_id, title, project_id, seq, org_id, owner_id, initiative_type,
                )
                # Scaffold the spec at version 0 directly. A brand-new spec has no prior
                # row to guard, so this doesn't bypass the optimistic lock — the first real
                # edit (via 0002) reads v0 and moves it to v1.
                await conn.execute(
                    """INSERT INTO specs (initiative_id, version, doc, updated_at)
                       VALUES ($1, 0, $2, now())""",
                    new_id, spec.model_dump_json(),
                )
        return Initiative(
            id=new_id, title=title, state="draft",
            initiative_type=initiative_type,
            project_id=project_id, seq=seq, org_id=org_id, owner_id=owner_id,
        )

    async def update_initiative_title(self, initiative_id: str, title: str) -> None:
        """Update the initiative row's title after background shaping resolves the LLM title."""
        await self.pg.execute(
            "UPDATE initiatives SET title = $1, updated_at = now() WHERE id = $2",
            title, initiative_id,
        )

    async def get_initiative(self, initiative_id: str) -> Initiative | None:
        """The initiative's lifecycle context — surfaced alongside the spec on MCP get_spec
        so an executor grounds itself in the lifecycle state before acting (D1 / 0004)."""
        row = await self.pg.fetchrow(
            """SELECT id, title, state, initiative_type, project_id, seq, org_id, owner_id,
                      created_at, updated_at
               FROM initiatives WHERE id = $1""",
            initiative_id,
        )
        return _initiative_from_row(row) if row else None

    async def get_initiative_by_seq(self, project_id: str, seq: int) -> Initiative | None:
        """Find an initiative by its per-project sequence number (0012 u5) — the resolution
        behind the short id BD-7 / the URL key bd-7-slug."""
        row = await self.pg.fetchrow(
            """SELECT id, title, state, initiative_type, project_id, seq, org_id, owner_id,
                      created_at, updated_at
               FROM initiatives WHERE project_id = $1 AND seq = $2""",
            project_id, seq,
        )
        return _initiative_from_row(row) if row else None

    _SHORT_REF = re.compile(r"^[A-Za-z]+-(\d+)(?:-.*)?$")

    async def resolve_initiative(self, project_id: str, ref: str) -> Initiative | None:
        """Resolve a URL ref within a project to its initiative (0012 u5/a10). Accepts the new
        short form (`bd-7-slug` / `bd-7`) — prefix + per-project seq — and, for backward
        compatibility, a legacy long initiative id, so old links still land (then redirect)."""
        m = self._SHORT_REF.match(ref)
        if m:
            by_seq = await self.get_initiative_by_seq(project_id, int(m.group(1)))
            if by_seq is not None:
                return by_seq
        legacy = await self.get_initiative(ref)
        return legacy if legacy is not None and legacy.project_id == project_id else None

    async def archive_initiative(self, initiative_id: str, reason: str) -> None:
        """Soft-archive an initiative (0013 follow-up): the spec, units, decisions, and memory
        stay on disk; archived_at hides it from every active list. Idempotent — re-archiving a
        already-archived initiative is a no-op. Raises NotFoundError if it doesn't exist."""
        result = await self.pg.execute(
            """UPDATE initiatives
                  SET archived_at     = COALESCE(archived_at, now()),
                      archived_reason = COALESCE(archived_reason, $2),
                      updated_at      = now()
                WHERE id = $1""",
            initiative_id, reason,
        )
        if result == "UPDATE 0":
            raise NotFoundError(f"no initiative {initiative_id}")

    async def list_initiatives(self) -> list[Initiative]:
        """Every active initiative that has a spec — the dashboard's feed (0004 a3). Most
        recently updated first. Archived initiatives are hidden by design (0013 follow-up)."""
        rows = await self.pg.fetch(
            """SELECT i.id, i.title, i.state, i.initiative_type, i.project_id, i.seq,
                      i.org_id, i.owner_id, i.created_at, i.updated_at
               FROM initiatives i
               JOIN specs s ON s.initiative_id = i.id
               WHERE i.archived_at IS NULL
               ORDER BY i.updated_at DESC, i.id"""
        )
        return [_initiative_from_row(r) for r in rows]

    async def _recompute_state(self, initiative_id: str) -> None:
        """Re-infer the four-stage lifecycle state (BD-5 u4) from criteria verification status
        and the learn record, then persist it on both the initiative row and the spec JSONB.

        Draft → Building: any criterion has had evidence submitted (evidence_submitted,
            verified, or changes_requested).
        Building → Learning: every criterion is verified.
        Learning → Complete: every criterion is verified AND a learn record exists.
        Learning → Complete (skip): via explicit mark_complete_without_learnings — not here.

        The spec row is locked FOR UPDATE before reading so that the version bump is atomic
        with the state patch. Any concurrent save_spec that loaded an older version will see
        a StaleSpecError (409) rather than silently overwriting the new state.
        """
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT version, doc FROM specs WHERE initiative_id = $1 FOR UPDATE",
                    initiative_id,
                )
                if row is None:
                    return
                spec = Spec.model_validate_json(row["doc"])
                criteria = spec.acceptance

                has_learn = bool(await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM memory WHERE initiative_id = $1)",
                    initiative_id,
                ))

                EVIDENCE_SEEN = {"evidence_submitted", "verified", "changes_requested"}
                if not criteria:
                    new_state = "complete" if has_learn else "draft"
                elif all(c.verification_status == "verified" for c in criteria) and has_learn:
                    new_state = "complete"
                elif all(c.verification_status == "verified" for c in criteria):
                    new_state = "learning"
                elif any(c.verification_status in EVIDENCE_SEEN for c in criteria):
                    new_state = "building"
                else:
                    new_state = "draft"

                new_version = row["version"] + 1
                await conn.execute(
                    "UPDATE initiatives SET state = $2, updated_at = now() WHERE id = $1",
                    initiative_id, new_state,
                )
                # Patch state and bump version atomically so save_spec detects the change.
                await conn.execute(
                    """UPDATE specs
                       SET version = $3,
                           doc = doc || jsonb_build_object('state', $2::text, 'version', $3::int),
                           updated_at = now()
                       WHERE initiative_id = $1""",
                    initiative_id, new_state, new_version,
                )

    # --- projects: group initiatives under a strategic intent (0010 u1) ------
    async def create_project(
        self, name: str, intent: str = "", prefix: str | None = None
    ) -> Project:
        """Create a project whose ID is the slug of its name (BD-11). The name must be unique
        (enforced by idx_projects_name); a duplicate raises ValidationError. `prefix` overrides
        the auto-derived initiative handle (0013 u2); collisions are disambiguated by suffixing."""
        slug = slugify(name) or "project"
        # the short handle for this project's initiatives (0012 u5); keep it unique so BD-7 is
        # unambiguous — disambiguate a collision by appending a number (BD, BD2, BD3, …). A
        # user-supplied prefix is normalised to the same shape (uppercase alphanumerics).
        cleaned = re.sub(r"[^A-Za-z0-9]", "", prefix or "").upper()
        base_prefix = cleaned or derive_prefix(name)
        pfx, m = base_prefix, 2
        while await self.pg.fetchval(
            "SELECT 1 FROM projects WHERE upper(prefix) = upper($1)", pfx
        ):
            pfx, m = f"{base_prefix}{m}", m + 1
        proj = Project(id=slug, name=name, prefix=pfx, intent=intent)
        try:
            await self.pg.execute(
                """INSERT INTO projects (id, name, prefix, intent, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, now(), now())""",
                proj.id, proj.name, proj.prefix, proj.intent,
            )
        except asyncpg.UniqueViolationError:
            raise ValidationError(f"a project named '{name}' already exists")
        return proj  # onboarding_dismissed and archived default to False/NULL on new projects

    async def archive_project(self, project_id: str) -> Project:
        """Archive a project (BD-11, item_cef8f182b12e). Idempotent — re-archiving is a no-op."""
        row = await self.pg.fetchrow(
            """UPDATE projects
               SET archived_at = COALESCE(archived_at, now()), updated_at = now()
               WHERE id = $1
               RETURNING id, name, prefix, intent, onboarding_dismissed, archived_at, created_at, updated_at""",
            project_id,
        )
        if row is None:
            raise NotFoundError(f"no project {project_id}")
        return _project_from_row(row)

    async def unarchive_project(self, project_id: str) -> Project:
        """Restore an archived project to active state (BD-11, item_2e81fe09d18d)."""
        row = await self.pg.fetchrow(
            """UPDATE projects
               SET archived_at = NULL, updated_at = now()
               WHERE id = $1
               RETURNING id, name, prefix, intent, onboarding_dismissed, archived_at, created_at, updated_at""",
            project_id,
        )
        if row is None:
            raise NotFoundError(f"no project {project_id}")
        return _project_from_row(row)

    async def update_project(self, project_id: str, *, intent: str) -> Project:
        """Edit a project's intent inline from the dashboard (0013 u2). Raises if it's gone."""
        row = await self.pg.fetchrow(
            """UPDATE projects SET intent = $2, updated_at = now()
               WHERE id = $1
               RETURNING id, name, prefix, intent, onboarding_dismissed, archived_at, created_at, updated_at""",
            project_id, intent,
        )
        if row is None:
            raise NotFoundError(f"no project {project_id}")
        return _project_from_row(row)

    async def dismiss_project_onboarding(self, project_id: str) -> Project:
        """Mark the onboarding hint as dismissed for this project (BD-9, item_b8b031fbfe0f)."""
        row = await self.pg.fetchrow(
            """UPDATE projects SET onboarding_dismissed = TRUE, updated_at = now()
               WHERE id = $1
               RETURNING id, name, prefix, intent, onboarding_dismissed, archived_at, created_at, updated_at""",
            project_id,
        )
        if row is None:
            raise NotFoundError(f"no project {project_id}")
        return _project_from_row(row)

    async def reset_project_onboarding(self, project_id: str) -> Project:
        """Re-enable the onboarding hint (BD-9, item_97b5c68fb7bd — flow must be re-triggerable)."""
        row = await self.pg.fetchrow(
            """UPDATE projects SET onboarding_dismissed = FALSE, updated_at = now()
               WHERE id = $1
               RETURNING id, name, prefix, intent, onboarding_dismissed, archived_at, created_at, updated_at""",
            project_id,
        )
        if row is None:
            raise NotFoundError(f"no project {project_id}")
        return _project_from_row(row)

    async def get_project(self, project_id: str) -> Project | None:
        row = await self.pg.fetchrow(
            "SELECT id, name, prefix, intent, onboarding_dismissed, archived_at, created_at, updated_at FROM projects WHERE id = $1",
            project_id,
        )
        return _project_from_row(row) if row else None

    async def list_projects(self) -> list[Project]:
        """Every project, newest first — the level above the dashboard (0010 a2)."""
        rows = await self.pg.fetch(
            """SELECT id, name, prefix, intent, onboarding_dismissed, archived_at, created_at, updated_at
               FROM projects ORDER BY created_at DESC, id"""
        )
        return [_project_from_row(r) for r in rows]

    async def list_project_initiatives(self, project_id: str) -> list[Initiative]:
        """The active initiatives grouped under a project (0010 a2/a7), most recently updated
        first. Archived initiatives are hidden (0013 follow-up)."""
        rows = await self.pg.fetch(
            """SELECT i.id, i.title, i.state, i.initiative_type, i.project_id, i.seq,
                      i.org_id, i.owner_id, i.created_at, i.updated_at
               FROM initiatives i
               JOIN specs s ON s.initiative_id = i.id
               WHERE i.project_id = $1 AND i.archived_at IS NULL
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
        strategic intent + token-conscious summaries of its sibling initiatives (title, state,
        headline confirmed constraints + count, most recent resolved decision). `exclude` drops
        the initiative in focus. Returns None if the project is gone. NOT full specs — the
        Advisor retrieves specifics on demand via project-scoped get_context (u4)."""
        proj = await self.get_project(project_id)
        if proj is None:
            return None
        rows = await self.pg.fetch(
            """SELECT i.id, i.seq, i.state, s.doc
               FROM initiatives i
               JOIN specs s ON s.initiative_id = i.id
               WHERE i.project_id = $1 AND i.archived_at IS NULL
                 AND ($2::text IS NULL OR i.id <> $2)
               ORDER BY i.updated_at DESC, i.id
               LIMIT $3""",
            project_id, exclude, sibling_limit,
        )
        # the most recent resolved decision per sibling, in one pass (DISTINCT ON)
        dec_rows = await self.pg.fetch(
            """SELECT DISTINCT ON (d.initiative_id) d.initiative_id, d.payload
               FROM decisions d
               JOIN initiatives i ON i.id = d.initiative_id
               WHERE i.project_id = $1 AND i.archived_at IS NULL
                 AND ($2::text IS NULL OR i.id <> $2)
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
            project_id=proj.id, name=proj.name, prefix=proj.prefix,
            intent=proj.intent, siblings=siblings,
        )

    async def count_open_decisions(self, project_id: str) -> int:
        """Open escalations across every active initiative in a project — a whole-project
        aggregate for the dashboard (0010 a2). Archived initiatives are excluded."""
        return await self.pg.fetchval(
            """SELECT count(*) FROM decisions d
               JOIN initiatives i ON i.id = d.initiative_id
               WHERE i.project_id = $1 AND i.archived_at IS NULL AND d.status = 'open'""",
            project_id,
        )

    async def count_pending_drift_reports(self, project_id: str) -> int:
        """Pending drift reports across all memory for a project — a whole-project aggregate
        (BD-12). Includes memory from archived initiatives so no report goes unnoticed."""
        return await self.pg.fetchval(
            """SELECT count(*) FROM drift_reports dr
               JOIN memory m ON m.id = dr.memory_id
               JOIN initiatives i ON i.id = m.initiative_id
               WHERE i.project_id = $1 AND dr.status = 'pending'""",
            project_id,
        )

    async def get_project_attention(
        self, project_id: str
    ) -> dict[str, InitiativeAttention]:
        """Per-initiative attention counts for the project screen (0011 a8 / BD-12): for each
        initiative in the project, how many proposed spec items await confirm/reject, how many
        decisions are open, how many criteria have evidence_submitted, and how many pending drift
        reports are attributed to memory from that initiative. Computed in four set-based passes
        (no N+1): proposed items from the spec JSONB, decisions grouped, criteria from JSONB,
        and drift reports via the memory join."""
        # Single LATERAL pass over the JSONB: counts proposed items across all three
        # sections AND evidence-submitted criteria in one scan per spec document, replacing
        # the previous four correlated subqueries (three for proposed_items + one for
        # criteria_to_verify). LEFT JOIN LATERAL preserves initiatives with empty specs.
        jsonb_rows = await self.pg.fetch(
            """SELECT i.id,
                      max(s.doc->>'shaping_status') = 'pending' AS is_shaping,
                      coalesce(sum(CASE WHEN e->>'status' = 'proposed' THEN 1 END), 0)::int
                          AS proposed_items,
                      coalesce(sum(CASE WHEN e->>'verification_status' = 'evidence_submitted' AND sec = 'acceptance' THEN 1 END), 0)::int
                          AS criteria_to_verify
               FROM initiatives i
               JOIN specs s ON s.initiative_id = i.id
               LEFT JOIN LATERAL (
                   SELECT e, 'constraints' AS sec
                     FROM jsonb_array_elements(coalesce(s.doc->'constraints', '[]')) e
                   UNION ALL
                   SELECT e, 'discretion' AS sec
                     FROM jsonb_array_elements(coalesce(s.doc->'discretion', '[]')) e
                   UNION ALL
                   SELECT e, 'acceptance' AS sec
                     FROM jsonb_array_elements(coalesce(s.doc->'acceptance', '[]')) e
               ) items ON true
               WHERE i.project_id = $1 AND i.archived_at IS NULL
               GROUP BY i.id""",
            project_id,
        )
        dec_rows = await self.pg.fetch(
            """SELECT d.initiative_id AS id, count(*) AS n
               FROM decisions d JOIN initiatives i ON i.id = d.initiative_id
               WHERE i.project_id = $1 AND i.archived_at IS NULL AND d.status = 'open'
               GROUP BY d.initiative_id""",
            project_id,
        )
        # BD-12: count pending drift reports attributed to memory from each initiative.
        drift_rows = await self.pg.fetch(
            """SELECT m.initiative_id AS id, count(*) AS n
               FROM drift_reports dr
               JOIN memory m ON m.id = dr.memory_id
               JOIN initiatives i ON i.id = m.initiative_id
               WHERE i.project_id = $1 AND dr.status = 'pending'
               GROUP BY m.initiative_id""",
            project_id,
        )
        decisions = {r["id"]: r["n"] for r in dec_rows}
        drifts = {r["id"]: r["n"] for r in drift_rows}
        return {
            r["id"]: InitiativeAttention(
                proposed_items=r["proposed_items"],
                open_decisions=decisions.get(r["id"], 0),
                criteria_to_verify=r["criteria_to_verify"],
                drift_reports=drifts.get(r["id"], 0),
                is_shaping=bool(r["is_shaping"]),
            )
            for r in jsonb_rows
        }

    async def assign_initiative_to_project(
        self, initiative_id: str, project_id: str
    ) -> Initiative:
        """Move an initiative to a (different) project. Both must exist. There is no detach —
        every initiative belongs to a project (no orphan specs)."""
        if await self.get_initiative(initiative_id) is None:
            raise NotFoundError(f"no initiative {initiative_id}")
        if await self.get_project(project_id) is None:
            raise NotFoundError(f"no project {project_id}")
        # Moving projects renumbers: the per-project seq is unique, so allocate a fresh one in the
        # target (the short id is per-project — a move necessarily reassigns it).
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT 1 FROM projects WHERE id = $1 FOR UPDATE", project_id)
                seq: int = await conn.fetchval(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM initiatives WHERE project_id = $1",
                    project_id,
                )
                await conn.execute(
                    "UPDATE initiatives SET project_id = $2, seq = $3, updated_at = now() "
                    "WHERE id = $1",
                    initiative_id, project_id, seq,
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

    async def agent_resolve_decision(
        self,
        d: Decision,
        initiative_id: str,
        *,
        chosen: str,
        rationale: str,
        discretion_item_id: str,
    ) -> Decision:
        """BD-13 Discretion Auditor path: save a decision as agent-resolved without creating
        an attention item or publishing to the human's steering rail.

        The decision is durably persisted with resolver_type='agent' so it appears in the
        decision log — distinguished from human-resolved — but never surfaces as an open
        escalation waiting for human judgment."""
        d.chosen = chosen
        d.rationale = rationale
        d.decided_by = f"auditor:{discretion_item_id}"
        d.resolver_type = "agent"
        d.status = "resolved"
        d.resolved_at = _now()
        await self.pg.execute(
            """INSERT INTO decisions (id, initiative_id, payload, status, created_at, resolved_at)
               VALUES ($1, $2, $3, 'resolved', now(), now())""",
            d.id, initiative_id, d.model_dump_json(),
        )
        # embed the reasoning async + best-effort so it's retrievable via get_context
        self._spawn(lambda: self.embed_decision(d.id))
        return d

    async def count_human_resolved_decisions(self, initiative_id: str) -> int:
        """BD-13: count decisions resolved by a human (not the Discretion Auditor).
        Used to compute the steering-ratio threshold (5+ → surface observation to Advisor)."""
        rows = await self.pg.fetch(
            "SELECT payload FROM decisions WHERE initiative_id = $1 AND status = 'resolved'",
            initiative_id,
        )
        return sum(
            1
            for r in rows
            if Decision.model_validate_json(r["payload"]).resolver_type != "agent"
        )

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
        d.resolver_type = "human"  # BD-13: mark as human-resolved for steering-ratio count
        d.status, d.resolved_at = "resolved", _now()

        await self.pg.execute(
            """UPDATE decisions
               SET payload = $2, status = 'resolved', resolved_at = now()
               WHERE id = $1""",
            decision_id, d.model_dump_json(),
        )
        # wake any agent parked on this exact decision — push, not poll
        await self.redis.publish(f"decision:{decision_id}", d.model_dump_json())
        # embed the resolved reasoning into memory, async + best-effort (0005 constraint 3):
        # it must not block (or break) the resolve. A failure leaves a null embedding for the
        # backfill to pick up.
        self._spawn(lambda: self.embed_decision(decision_id))
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
        except TimeoutError:
            # asyncio.timeout raises TimeoutError; convert to the domain exception so
            # callers (MCP wait_for_decision) get the expected type, not a bare TimeoutError.
            pass
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

    def _spawn(self, factory: Callable[[], Coroutine]) -> None:
        """Run an embed in the background, kept referenced so the loop won't GC it.
        Best-effort: a missing key or API hiccup is logged, never raised at the caller
        (0005 constraint 3 — resolving / completing must not block or break).
        Retries up to 3 times with exponential backoff before giving up."""
        task = asyncio.create_task(self._safe(factory))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    @staticmethod
    async def _safe(factory: Callable[[], Coroutine]) -> None:
        for attempt in range(3):
            try:
                await factory()
                return
            except Exception:
                if attempt == 2:
                    logger.warning("background embed task failed after 3 attempts", exc_info=True)
                else:
                    await asyncio.sleep(2**attempt)

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
        *,
        initiative_type: InitiativeType = "engineering",
    ) -> Memory:
        """Write a completed initiative's memory row and embed it async (constraint 3:
        completing Learn must not block). Append-only — every call is a new row.
        BD-15: `initiative_type` is stored so context hits expose whether the learning
        came from a research or engineering initiative."""
        mem = Memory(
            initiative_id=initiative_id, summary=summary, learnings=learnings, outcome=outcome,
            initiative_type=initiative_type,
        )
        await self.pg.execute(
            """INSERT INTO memory
                   (id, initiative_id, summary, learnings, outcome, initiative_type, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, now())""",
            mem.id, initiative_id, summary, learnings,
            json.dumps(outcome) if outcome is not None else None,
            initiative_type,
        )
        # a learn record can complete the initiative (all criteria verified + learnings captured — 0011 a2)
        await self._recompute_state(initiative_id)
        self._spawn(lambda: self.embed_memory(mem.id))
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
            """SELECT id, initiative_id, summary, learnings, outcome, initiative_type,
                      created_at, last_verified_at
               FROM memory WHERE initiative_id = $1 ORDER BY created_at DESC""",
            initiative_id,
        )
        return [_memory_from_row(r) for r in rows]

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Fetch a single memory entry by id. Returns None if not found."""
        row = await self.pg.fetchrow(
            """SELECT id, initiative_id, summary, learnings, outcome, initiative_type,
                      created_at, last_verified_at
               FROM memory WHERE id = $1""",
            memory_id,
        )
        return _memory_from_row(row) if row else None

    # --- BD-12: drift reports — agent-flagged memory discrepancies, human-gated --------
    async def create_drift_report(
        self,
        memory_id: str,
        current_evidence: str,
        is_obsolete: bool,
        initiative_id: str | None = None,
        quality: dict | None = None,
    ) -> DriftReport:
        """Record an agent's report that a memory entry may no longer reflect the codebase.
        Validates that the memory entry exists; raises NotFoundError otherwise so the MCP tool
        can surface a descriptive error and write no record (BD-12 AC item_78571d0266a6).
        `quality` is the serialised JudgeResult from the LLM-as-judge evaluation — None if
        the judge was skipped or unavailable."""
        exists = await self.pg.fetchval("SELECT 1 FROM memory WHERE id = $1", memory_id)
        if not exists:
            raise NotFoundError(f"no memory entry with id {memory_id!r}")
        report = DriftReport(
            memory_id=memory_id,
            initiative_id=initiative_id,
            current_evidence=current_evidence,
            is_obsolete=is_obsolete,
            quality=quality,
        )
        await self.pg.execute(
            """INSERT INTO drift_reports
               (id, memory_id, initiative_id, current_evidence, is_obsolete, status, quality, created_at)
               VALUES ($1, $2, $3, $4, $5, 'pending', $6, now())""",
            report.id, memory_id, initiative_id, current_evidence, is_obsolete,
            json.dumps(quality) if quality is not None else None,
        )
        return report

    async def list_drift_reports_by_project(
        self, project_id: str, *, status: DriftReportStatus | None = None
    ) -> list[DriftReport]:
        """All drift reports for a project's memory (via memory → initiative → project).
        Optionally filtered by status. Ordered newest-first."""
        rows = await self.pg.fetch(
            """SELECT dr.id, dr.memory_id, dr.initiative_id, dr.current_evidence,
                      dr.is_obsolete, dr.status, dr.resolution_note, dr.quality,
                      dr.created_at, dr.resolved_at
               FROM drift_reports dr
               JOIN memory m ON m.id = dr.memory_id
               JOIN initiatives i ON i.id = m.initiative_id
               WHERE i.project_id = $1
                 AND ($2::text IS NULL OR dr.status = $2)
               ORDER BY dr.created_at DESC""",
            project_id, status,
        )
        return [_drift_report_from_row(r) for r in rows]

    async def resolve_drift_report(
        self,
        report_id: str,
        action: DriftReportStatus,
        memory_update: dict | None = None,
        resolution_note: str | None = None,
    ) -> DriftReport:
        """Human resolves a drift report with one of: approved, dismissed, initiative_created.
        On 'approved', optionally patches the memory entry's summary/learnings and stamps
        last_verified_at. Memory is never mutated without explicit human approval."""
        row = await self.pg.fetchrow(
            """SELECT dr.*, m.id AS mem_id FROM drift_reports dr
               JOIN memory m ON m.id = dr.memory_id WHERE dr.id = $1""",
            report_id,
        )
        if row is None:
            raise NotFoundError(f"no drift report with id {report_id!r}")
        if row["status"] != "pending":
            raise ValidationError(f"drift report {report_id!r} is already resolved")
        if action not in ("approved", "dismissed", "initiative_created"):
            raise ValidationError(f"unknown resolution action {action!r}")

        async with self.pg.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """UPDATE drift_reports
                       SET status = $2, resolution_note = $3, resolved_at = now()
                       WHERE id = $1""",
                    report_id, action, resolution_note,
                )
                if action == "approved":
                    if memory_update:
                        if "summary" in memory_update:
                            await conn.execute(
                                "UPDATE memory SET summary = $2 WHERE id = $1",
                                row["mem_id"], memory_update["summary"],
                            )
                        if "learnings" in memory_update:
                            await conn.execute(
                                "UPDATE memory SET learnings = $2 WHERE id = $1",
                                row["mem_id"], memory_update.get("learnings"),
                            )
                # stamp last_verified_at on both approved and dismissed — a dismissal means
                # "human reviewed this," so it should not re-appear in the next audit cycle.
                # Content is only mutated on approved (constraint item_f3ddf0841091 holds).
                if action in ("approved", "dismissed"):
                    await conn.execute(
                        "UPDATE memory SET last_verified_at = now() WHERE id = $1",
                        row["mem_id"],
                    )

        updated = await self.pg.fetchrow(
            """SELECT id, memory_id, initiative_id, current_evidence, is_obsolete,
                      status, resolution_note, quality, created_at, resolved_at
               FROM drift_reports WHERE id = $1""",
            report_id,
        )
        return _drift_report_from_row(updated)

    # --- BD-17: heuristics — first-class memory type, append-only with supersession ------

    async def create_heuristic(
        self,
        initiative_id: str,
        rule: str,
        *,
        project_id: str | None = None,
        tags: list[str] | None = None,
        replaces: str | None = None,
    ) -> Heuristic:
        """Write a new heuristic row and embed it async. Append-only — every call is a new
        row. If `replaces` is given, the old heuristic is marked superseded by initiative_id
        (constraint item_580f56224a2b) and the back-reference is stored here (item_47ba758192ea)."""
        heur = Heuristic(
            initiative_id=initiative_id,
            project_id=project_id,
            rule=rule,
            tags=tags or [],
            replaces=replaces,
        )
        await self.pg.execute(
            """INSERT INTO heuristics
                   (id, initiative_id, project_id, rule, tags, replaces, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, now())""",
            heur.id, initiative_id, project_id, rule, tags or [], replaces,
        )
        if replaces:
            await self.supersede_heuristic(replaces, initiative_id)
        self._spawn(lambda hid=heur.id: self.embed_heuristic(hid))
        return heur

    async def supersede_heuristic(self, heuristic_id: str, superseding_initiative_id: str) -> None:
        """Mark a heuristic as superseded. The row stays readable (item_580f56224a2b) but
        is excluded from active retrieval (constraint item_74a52b7067a3)."""
        await self.pg.execute(
            "UPDATE heuristics SET superseded_by = $2 WHERE id = $1 AND superseded_by IS NULL",
            heuristic_id, superseding_initiative_id,
        )

    async def embed_heuristic(self, heuristic_id: str) -> bool:
        row = await self.pg.fetchrow("SELECT rule FROM heuristics WHERE id = $1", heuristic_id)
        if row is None:
            return False
        [vec] = await self._get_embedder().embed([row["rule"]])
        await self.pg.execute(
            "UPDATE heuristics SET embedding = $2::vector WHERE id = $1",
            heuristic_id, _vector_literal(vec),
        )
        return True

    async def get_heuristic(self, heuristic_id: str) -> Heuristic | None:
        row = await self.pg.fetchrow(
            "SELECT id, initiative_id, project_id, rule, tags, superseded_by, replaces, created_at "
            "FROM heuristics WHERE id = $1",
            heuristic_id,
        )
        return _heuristic_from_row(row) if row else None

    async def list_heuristics(
        self,
        *,
        project_id: str | None = None,
        initiative_id: str | None = None,
        active_only: bool = True,
    ) -> list[Heuristic]:
        """List heuristics. `active_only=True` (default) excludes superseded entries.
        Pass `active_only=False` to include superseded entries for history/audit."""
        wheres = []
        params: list = []
        p = 1
        if project_id is not None:
            wheres.append(f"project_id = ${p}")
            params.append(project_id)
            p += 1
        if initiative_id is not None:
            wheres.append(f"initiative_id = ${p}")
            params.append(initiative_id)
            p += 1
        if active_only:
            wheres.append("superseded_by IS NULL")
        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        rows = await self.pg.fetch(
            f"SELECT id, initiative_id, project_id, rule, tags, superseded_by, replaces, created_at "
            f"FROM heuristics {where_clause} ORDER BY created_at DESC",
            *params,
        )
        return [_heuristic_from_row(r) for r in rows]

    async def list_memory_for_audit(
        self, project_id: str, staleness_days: int = 30
    ) -> list[Memory]:
        """Memory entries for the project whose last_verified_at is older than staleness_days,
        or NULL (never verified). Never returns the unfiltered memory table — the staleness
        filter is non-optional (BD-12 constraint item_444e2af3a93b)."""
        rows = await self.pg.fetch(
            """SELECT m.id, m.initiative_id, m.summary, m.learnings, m.outcome,
                      m.initiative_type, m.created_at, m.last_verified_at
               FROM memory m
               JOIN initiatives i ON i.id = m.initiative_id
               WHERE i.project_id = $1
                 AND (m.last_verified_at IS NULL
                      OR m.last_verified_at < now() - ($2 * interval '1 day'))
               ORDER BY m.last_verified_at ASC NULLS FIRST""",
            project_id, staleness_days,
        )
        return [_memory_from_row(r) for r in rows]

    async def get_context(
        self,
        query: str,
        limit: int = 8,
        *,
        project_id: str,
        include_superseded_heuristics: bool = False,
    ) -> list[ContextHit]:
        """Similarity search over the memory corpus — resolved decisions + completed-
        initiative memory (D2 scope) — so an executor shaping or building the next feature
        retrieves relevant prior patterns (0005 a6/a7/a8). Ranked by cosine similarity; rows
        without an embedding are skipped.

        0010 constraint 4: search WITHIN the project first; only if those are insufficient to
        fill `limit` does it fall back to the rest of the corpus (outside the project). Each
        hit is tagged with its scope (project / global) and its source initiative.

        BD-17: `include_superseded_heuristics=True` includes superseded heuristic entries with
        `superseded_by` set so the shaping classifier can detect and flag them. The MCP tool
        always passes the default (False) — superseded entries must not surface as active guidance
        (constraint item_74a52b7067a3)."""
        if not query.strip():
            return []
        [qvec] = await self._get_embedder().embed([query])
        project_hits = await self._context_search(
            qvec, limit, project_id=project_id,
            include_superseded_heuristics=include_superseded_heuristics,
        )
        for h in project_hits:
            h.scope = "project"
        if len(project_hits) >= limit:
            return project_hits
        # project results are insufficient — fill the rest from OUTSIDE the project (a4)
        fallback = await self._context_search(
            qvec, limit - len(project_hits), exclude_project=project_id,
            include_superseded_heuristics=include_superseded_heuristics,
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
        include_superseded_heuristics: bool = False,
    ) -> list[ContextHit]:
        """One ranked pass over the corpus. `project_id` restricts to a project's initiatives;
        `exclude_project` restricts to everything outside one (the global fallback). The join
        to initiatives never drops rows — decisions/memory cascade-delete with their
        initiative, so every embedded row has a live parent.

        BD-12: `mem_id` is exposed for memory hits so we can batch-lookup pending drift reports.
        BD-17: heuristics are included in the UNION. Active heuristics (superseded_by IS NULL)
        are always included. Superseded heuristics are included only when
        `include_superseded_heuristics=True` (used by the shaping classifier to detect and flag
        items grounded in stale heuristics — constraint item_9311fd139032)."""
        # The heuristic sub-query varies based on include_superseded_heuristics.
        heur_filter = "" if include_superseded_heuristics else "AND superseded_by IS NULL"
        rows = await self.pg.fetch(
            f"""
            SELECT q.type, q.initiative_id, q.txt, q.dist, q.mem_id, q.init_type,
                   q.heur_id, q.heur_superseded_by FROM (
                SELECT 'decision' AS type, initiative_id,
                       concat_ws(' — ', payload->>'question',
                           NULLIF('Chosen: ' || coalesce(payload->>'chosen', ''), 'Chosen: '),
                           NULLIF('Rationale: ' || coalesce(payload->>'rationale', ''), 'Rationale: ')
                       ) AS txt,
                       embedding <=> $1::vector AS dist,
                       NULL::text AS mem_id,
                       NULL::text AS init_type,
                       NULL::text AS heur_id,
                       NULL::text AS heur_superseded_by
                  FROM decisions WHERE embedding IS NOT NULL
                UNION ALL
                SELECT 'memory' AS type, initiative_id,
                       concat_ws(' — ', summary,
                           NULLIF('Learnings: ' || coalesce(learnings, ''), 'Learnings: ')
                       ) AS txt,
                       embedding <=> $1::vector AS dist,
                       id AS mem_id,
                       initiative_type AS init_type,
                       NULL::text AS heur_id,
                       NULL::text AS heur_superseded_by
                  FROM memory WHERE embedding IS NOT NULL
                UNION ALL
                SELECT 'heuristic' AS type, initiative_id,
                       rule AS txt,
                       embedding <=> $1::vector AS dist,
                       NULL::text AS mem_id,
                       NULL::text AS init_type,
                       id AS heur_id,
                       superseded_by AS heur_superseded_by
                  FROM heuristics WHERE embedding IS NOT NULL {heur_filter}
            ) q
            JOIN initiatives i ON i.id = q.initiative_id
            WHERE (q.type IN ('decision', 'memory') AND i.state = 'complete'
                   OR q.type = 'heuristic')
              AND ($2::text IS NULL OR i.project_id = $2)
              AND ($3::text IS NULL OR i.project_id IS DISTINCT FROM $3)
            ORDER BY q.dist
            LIMIT $4
            """,
            _vector_literal(qvec), project_id, exclude_project, limit,
        )
        # batch-lookup pending drift reports for the memory hits in one round-trip
        memory_ids = [r["mem_id"] for r in rows if r["mem_id"]]
        pending_drift: set[str] = set()
        if memory_ids:
            pending_rows = await self.pg.fetch(
                "SELECT DISTINCT memory_id FROM drift_reports "
                "WHERE memory_id = ANY($1) AND status = 'pending'",
                memory_ids,
            )
            pending_drift = {r["memory_id"] for r in pending_rows}
        return [
            ContextHit(
                initiative_id=r["initiative_id"],
                type=r["type"],
                text=r["txt"],
                score=round(1.0 - float(r["dist"]), 4),
                has_pending_drift=r["mem_id"] in pending_drift if r["mem_id"] else False,
                initiative_type=r["init_type"],  # BD-15: None for decision/heuristic hits
                heuristic_id=r["heur_id"],        # BD-17: set for heuristic hits
                superseded_by=r["heur_superseded_by"],  # BD-17: set for superseded heuristics
            )
            for r in rows
        ]

    # Conversation history is no longer stored server-side (spec uvama): it lives in the
    # browser's IndexedDB. The frontend sends a windowed slice with each Advisor call and the
    # backend discards it after replying — there is deliberately no message read/write here.

    # --- BD-5 u2: criteria-as-tracking (submit_evidence, get_criteria_status) -----------
    async def submit_evidence(
        self,
        initiative_id: str,
        criteria_results: list[dict],
    ) -> Spec:
        """Submit evidence against acceptance criteria (BD-5 u2). All-or-nothing: if any
        criterion_id is not found the whole call is rejected before any mutation. Sets
        verification_status to evidence_submitted on each targeted criterion and bumps the
        spec version via save_spec (the existing optimistic-lock guard applies)."""
        spec = await self.get_spec(initiative_id)
        if spec is None:
            raise NotFoundError(f"no spec for initiative {initiative_id}")

        criterion_map = {c.id: c for c in spec.acceptance}
        # validate all IDs before mutating anything
        unknown = [r["criterion_id"] for r in criteria_results if r["criterion_id"] not in criterion_map]
        if unknown:
            raise NotFoundError(
                f"criterion id(s) not found in {initiative_id}: {', '.join(unknown)}"
            )

        _MAX_EVIDENCE = 2000
        for r in criteria_results:
            c = criterion_map[r["criterion_id"]]
            c.verification_status = "evidence_submitted"
            raw = r.get("evidence") or None
            c.evidence = raw[:_MAX_EVIDENCE] if raw and len(raw) > _MAX_EVIDENCE else raw

        await self.save_spec(spec)
        await self._recompute_state(initiative_id)  # draft → building on first evidence
        return await self.get_spec(initiative_id) or spec

    async def transition_to_building(self, initiative_id: str) -> Initiative:
        """Manual 'start building' trigger (BD-5 u4): move a draft initiative to building.
        Only valid from draft — a no-op would be confusing so it's rejected from other states."""
        init = await self.get_initiative(initiative_id)
        if init is None:
            raise NotFoundError(f"no initiative {initiative_id}")
        if init.state != "draft":
            raise ValidationError(f"initiative is already {init.state}, not draft")
        await self.pg.execute(
            "UPDATE initiatives SET state = 'building', updated_at = now() WHERE id = $1",
            initiative_id,
        )
        await self.pg.execute(
            """UPDATE specs SET doc = jsonb_set(doc, '{state}', to_jsonb('building'::text)),
               updated_at = now() WHERE initiative_id = $1""",
            initiative_id,
        )
        return (await self.get_initiative(initiative_id)) or init

    async def revert_to_draft(self, initiative_id: str) -> Initiative:
        """Move a building initiative back to draft so the spec can be reshaped.
        Only valid from building — other states are rejected to avoid confusion.
        Criteria verification statuses are preserved; _recompute_state will push the
        initiative back to building the next time evidence is submitted."""
        init = await self.get_initiative(initiative_id)
        if init is None:
            raise NotFoundError(f"no initiative {initiative_id}")
        if init.state != "building":
            raise ValidationError(f"initiative is {init.state}, not building")
        await self.pg.execute(
            "UPDATE initiatives SET state = 'draft', updated_at = now() WHERE id = $1",
            initiative_id,
        )
        await self.pg.execute(
            """UPDATE specs SET doc = jsonb_set(doc, '{state}', to_jsonb('draft'::text)),
               updated_at = now() WHERE initiative_id = $1""",
            initiative_id,
        )
        return (await self.get_initiative(initiative_id)) or init

    async def mark_complete_without_learnings(self, initiative_id: str) -> Initiative:
        """Escape hatch: complete from learning without writing a learn record (BD-5 u4).
        Only valid from learning — the caller must have shown the friction warning:
        'Skipping reflection — nothing will be written to memory for this initiative.'"""
        init = await self.get_initiative(initiative_id)
        if init is None:
            raise NotFoundError(f"no initiative {initiative_id}")
        if init.state != "learning":
            raise ValidationError(f"initiative is in {init.state}, not learning")
        await self.pg.execute(
            "UPDATE initiatives SET state = 'complete', updated_at = now() WHERE id = $1",
            initiative_id,
        )
        await self.pg.execute(
            """UPDATE specs SET doc = jsonb_set(doc, '{state}', to_jsonb('complete'::text)),
               updated_at = now() WHERE initiative_id = $1""",
            initiative_id,
        )
        return (await self.get_initiative(initiative_id)) or init

    async def get_criteria_status(self, initiative_id: str) -> list[dict]:
        """Return all acceptance criteria with their current verification fields (BD-5 u2)."""
        spec = await self.get_spec(initiative_id)
        if spec is None:
            raise NotFoundError(f"no spec for initiative {initiative_id}")
        return [
            {
                "id": c.id,
                "text": c.text,
                "verification_status": c.verification_status,
                "evidence": c.evidence,
                "verdict": c.verdict,
                "feedback": c.feedback,
            }
            for c in spec.acceptance
        ]

    async def record_criterion_verdict(
        self,
        initiative_id: str,
        criterion_id: str,
        verdict: str,
        feedback: str | None = None,
    ) -> Spec:
        """Record a human verdict on a single criterion (BD-5 u3). Sets verdict + feedback,
        and transitions verification_status to verified or changes_requested accordingly."""
        spec = await self.get_spec(initiative_id)
        if spec is None:
            raise NotFoundError(f"no spec for initiative {initiative_id}")
        criterion_map = {c.id: c for c in spec.acceptance}
        if criterion_id not in criterion_map:
            raise NotFoundError(f"criterion {criterion_id} not found in {initiative_id}")
        c = criterion_map[criterion_id]
        c.verdict = verdict  # type: ignore[assignment]
        c.feedback = feedback or None
        c.verification_status = "verified" if verdict == "approved" else "changes_requested"
        await self.save_spec(spec)
        await self._recompute_state(initiative_id)  # building → learning when all verified
        return await self.get_spec(initiative_id) or spec

    # --- observations (BD-22) ------------------------------------------------
    async def replace_open_observations(
        self, project_id: str, contents: list[str]
    ) -> None:
        """Replace all open observations for a project with a fresh set (BD-22). Resolved
        observations are preserved. Idempotent: calling with an empty list just clears open ones."""
        async with self.pg.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM observations WHERE project_id = $1 AND status = 'open'",
                    project_id,
                )
                for c in contents:
                    obs = Observation(project_id=project_id, content=c)
                    await conn.execute(
                        """INSERT INTO observations (id, project_id, content, status, created_at)
                           VALUES ($1, $2, $3, 'open', now())""",
                        obs.id,
                        project_id,
                        obs.content,
                    )

    async def list_observations(self, project_id: str) -> list[Observation]:
        """All observations for a project, open first then resolved, newest first within each group."""
        rows = await self.pg.fetch(
            """SELECT id, project_id, content, status, resolved_initiative_id, created_at
               FROM observations
               WHERE project_id = $1
               ORDER BY (status = 'open') DESC, created_at DESC""",
            project_id,
        )
        return [_observation_from_row(r) for r in rows]

    async def resolve_observation(
        self, observation_id: str, initiative_id: str
    ) -> Observation:
        """Mark an observation as resolved and link it to the created initiative (BD-22).
        Idempotent: resolving an already-resolved observation updates the initiative link."""
        row = await self.pg.fetchrow(
            """UPDATE observations
               SET status = 'resolved', resolved_initiative_id = $2
               WHERE id = $1
               RETURNING id, project_id, content, status, resolved_initiative_id, created_at""",
            observation_id, initiative_id,
        )
        if row is None:
            raise NotFoundError(f"no observation {observation_id}")
        return _observation_from_row(row)

