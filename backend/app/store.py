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
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import asyncpg
from pydantic import BaseModel, ConfigDict, Field
from redis import asyncio as aioredis


# ----------------------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


# ----------------------------------------------------------------------------- models
Provenance = Literal["human", "ai_proposed", "ai_confirmed_by_human"]
ItemStatus = Literal["proposed", "confirmed", "retired"]
Stage = Literal["discover", "shape", "bet", "decompose", "implement", "verify", "learn"]


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


# ----------------------------------------------------------------------------- errors
class StaleSpecError(Exception):
    def __init__(self, initiative_id: str, expected: int, found: int):
        super().__init__(
            f"spec {initiative_id} changed under you (have v{expected}, db v{found})"
        )
        self.initiative_id, self.expected, self.found = initiative_id, expected, found


class DecisionTimeout(Exception):
    pass


# ----------------------------------------------------------------------------- store
SPEC_CACHE_TTL = 300  # seconds; cache is derived, so a short TTL is just a safety net


class SpecStore:
    def __init__(self, pg: asyncpg.Pool, redis: aioredis.Redis):
        self.pg = pg
        self.redis = redis

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
        # wake any agent parked on this exact decision — push, not poll
        await self.redis.publish(f"decision:{decision_id}", d.model_dump_json())
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
