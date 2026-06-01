"""Doen MCP server — the executor-facing seam, over stdio.

Decision 1 in spec 0001 chose stdio for local dogfooding and the OSS self-hosted
path: auth lives outside the protocol (local subprocess + env credentials), so no
OAuth resource server is needed. Run it as its own process — it owns its own
Postgres pool and Redis client and talks to the store directly, NOT through the
FastAPI app:

    python -m app.mcp_server

Exposes exactly the four tools spec 0001/a4 calls for: get_spec, raise_decision,
resolve_decision, and wait_for_decision (the "await a resolution" path — a push via
Redis pub/sub, not a poll loop). Resolution typically arrives from a different
client (the human's rail), which is why pub/sub across connections matters.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncpg
from mcp.server.fastmcp import Context, FastMCP
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.exceptions import DecisionTimeout, InvalidTransition
from app.models import CriterionResult, Decision, Submission, WorkUnit
from app.store import SpecStore


@dataclass
class Lifespan:
    store: SpecStore


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[Lifespan]:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis.ping()  # type: ignore  # redis.asyncio.ping is awaitable; stubs mistype it as sync
    try:
        yield Lifespan(store=SpecStore(pg, redis))
    finally:
        await pg.close()
        await redis.aclose()


mcp = FastMCP("doen", lifespan=lifespan)


def _store(ctx: Context) -> SpecStore:
    return ctx.request_context.lifespan_context.store


@mcp.tool()
async def get_spec(initiative_id: str, ctx: Context) -> dict:
    """Read the whole living spec for an initiative at its current version, plus the
    initiative's lifecycle context as `initiative: {id, title, stage}`. Ground yourself in
    intent, constraints, discretion, acceptance — and stage (don't reshape a spec already
    in `implement`) — before acting."""
    store = _store(ctx)
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise ValueError(f"no spec for initiative {initiative_id}")
    out = spec.model_dump()
    init = await store.get_initiative(initiative_id)
    out["initiative"] = (
        {"id": init.id, "title": init.title, "stage": init.stage} if init else None
    )
    return out


@mcp.tool()
async def raise_decision(
    initiative_id: str,
    question: str,
    options: list[str],
    ctx: Context,
    recommendation: str | None = None,
    unit_id: str | None = None,
) -> dict:
    """Surface a product/intent call that is outside the spec's constraints + discretion.
    Do not guess in code. Returns the open Decision; await it with wait_for_decision.
    Pass unit_id to park that work unit (blocked_on_decision) on this decision — resolving
    it later resumes the unit automatically."""
    d = Decision(question=question, options=options, recommendation=recommendation)
    store = _store(ctx)
    saved = await store.raise_decision(d, initiative_id)
    if unit_id is not None:
        await store.block_on_decision(unit_id, saved.id)
    return saved.model_dump()


@mcp.tool()
async def resolve_decision(
    decision_id: str,
    chosen: str,
    rationale: str,
    decided_by: str,
    ctx: Context,
) -> dict:
    """Record the human's verdict on an open decision and wake anyone awaiting it."""
    d = await _store(ctx).resolve_decision(decision_id, chosen, rationale, decided_by)
    return d.model_dump()


@mcp.tool()
async def wait_for_decision(decision_id: str, ctx: Context, timeout: float = 600) -> dict:
    """Block until a decision is resolved, then return it. Push via Redis pub/sub, not a
    poll loop. Raises if it is not resolved within `timeout` seconds."""
    try:
        d = await _store(ctx).wait_for_decision(decision_id, timeout=timeout)
    except DecisionTimeout:
        raise ValueError(f"decision {decision_id} not resolved within {timeout}s")
    return d.model_dump()


# --- work units (spec 0003): decompose, work, submit; the human confirms + judges ---
@mcp.tool()
async def propose_unit(
    spec_id: str,
    title: str,
    scope: str,
    criterion_ids: list[str],
    ctx: Context,
) -> dict:
    """Propose a work unit decomposed from a spec, naming the acceptance criteria it
    satisfies. It is created `proposed` — a human must confirm it before it is workable.
    You cannot confirm your own unit."""
    unit = WorkUnit(spec_id=spec_id, title=title, scope=scope, criterion_ids=criterion_ids)
    saved = await _store(ctx).create_unit(unit)
    return saved.model_dump()


@mcp.tool()
async def list_units(spec_id: str, ctx: Context, status: str | None = None) -> list[dict]:
    """List the work units for a spec (oldest first), optionally filtered by status."""
    units = await _store(ctx).list_units(spec_id, status)
    return [u.model_dump() for u in units]


@mcp.tool()
async def claim_unit(unit_id: str, ctx: Context) -> dict:
    """Claim a confirmed (ready) work unit to start building it: ready -> in_progress.
    Only a unit a human has confirmed can be claimed."""
    try:
        unit = await _store(ctx).claim_unit(unit_id)
    except KeyError:
        raise ValueError(f"no work unit {unit_id}")
    except InvalidTransition as e:
        raise ValueError(str(e))
    return unit.model_dump()


@mcp.tool()
async def report_progress(unit_id: str, note: str, ctx: Context) -> dict:
    """Update a unit's progress note — a lightweight heartbeat the human's spec view reflects."""
    try:
        unit = await _store(ctx).report_progress(unit_id, note)
    except KeyError:
        raise ValueError(f"no work unit {unit_id}")
    return unit.model_dump()


@mcp.tool()
async def submit_for_verification(
    unit_id: str,
    summary: str,
    criteria_results: list[dict],
    ctx: Context,
    artifacts: list[str] | None = None,
) -> dict:
    """Hand a unit back for the human to judge. Map your output to each acceptance criterion
    (result: pass / fail / needs_judgment, plus evidence). At least one result is required.
    The human judges intent-alignment — you cannot set your own verdict."""
    submission = Submission(
        summary=summary,
        criteria_results=[CriterionResult(**c) for c in criteria_results],
        artifacts=artifacts or [],
    )
    try:
        unit = await _store(ctx).submit_for_verification(unit_id, submission)
    except KeyError:
        raise ValueError(f"no work unit {unit_id}")
    except InvalidTransition as e:
        raise ValueError(str(e))
    return unit.model_dump()


@mcp.tool()
async def get_verification(unit_id: str, ctx: Context) -> dict:
    """Read the human's verdict on a submitted unit, or `pending` if not yet judged.
    This only ever returns a verdict a human gave — there is no self-approval path."""
    try:
        verdict = await _store(ctx).get_verification(unit_id)
    except KeyError:
        raise ValueError(f"no work unit {unit_id}")
    if verdict is None:
        return {"status": "pending"}
    return {"status": "judged", **verdict.model_dump()}


# --- organizational memory (spec 0005): retrieve relevant prior patterns -------------
@mcp.tool()
async def get_context(initiative_id: str, query: str, ctx: Context, limit: int = 8) -> dict:
    """Retrieve relevant prior patterns to ground the current work. Searches the memory
    corpus — resolved decisions and completed-initiative memory — across ALL initiatives,
    ranked by similarity to `query`. Call it while shaping or building so you reuse what
    was decided and learned before instead of re-deciding it. Each hit is source-attributed
    (which initiative, decision vs. memory) with a relevance score, so you can judge whether
    to trust it. `initiative_id` is your current grounding context; results deliberately
    include other initiatives."""
    hits = await _store(ctx).get_context(query, limit=limit)
    return {
        "initiative_id": initiative_id,
        "query": query,
        "hits": [h.model_dump() for h in hits],
    }


if __name__ == "__main__":
    mcp.run()
