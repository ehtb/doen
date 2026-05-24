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
from app.store import Decision, DecisionTimeout, SpecStore


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
    """Read the whole living spec for an initiative at its current version.
    Ground yourself in intent, constraints, discretion, and acceptance before acting."""
    spec = await _store(ctx).get_spec(initiative_id)
    if spec is None:
        raise ValueError(f"no spec for initiative {initiative_id}")
    return spec.model_dump()


@mcp.tool()
async def raise_decision(
    initiative_id: str,
    question: str,
    options: list[str],
    ctx: Context,
    recommendation: str | None = None,
) -> dict:
    """Surface a product/intent call that is outside the spec's constraints + discretion.
    Do not guess in code. Returns the open Decision; await it with wait_for_decision."""
    d = Decision(question=question, options=options, recommendation=recommendation)
    saved = await _store(ctx).raise_decision(d, initiative_id)
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


if __name__ == "__main__":
    mcp.run()
