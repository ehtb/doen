"""Backfill embeddings for decisions resolved before the memory slice (spec 0005, a3).

Every resolved decision is part of the retrievable corpus, but rows resolved before
this slice have a null embedding. This embeds them so no resolved decision is left
out of get_context. Idempotent — only touches rows whose embedding is still null.

Requires LLM_API_KEY (or whichever provider get_embedding_provider returns).

    cd backend && .venv/bin/python -m app.backfill_embeddings
"""

from __future__ import annotations

import asyncio

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.store import SpecStore


async def backfill_with(store: SpecStore, initiative_id: str | None = None) -> tuple[int, int]:
    """Embed every resolved decision whose embedding is still null. Optionally scoped
    to one initiative. Returns (embedded_count, still_null_count). The store carries
    the embedder, so tests pass a fake one and never hit the network."""
    where = "status = 'resolved' AND embedding IS NULL"
    args: tuple = ()
    if initiative_id is not None:
        where += " AND initiative_id = $1"
        args = (initiative_id,)
    rows = await store.pg.fetch(
        f"SELECT id FROM decisions WHERE {where} ORDER BY created_at", *args
    )
    done = 0
    for r in rows:
        if await store.embed_decision(r["id"]):
            done += 1
    remaining = await store.pg.fetchval(
        f"SELECT count(*) FROM decisions WHERE {where}", *args
    )
    return done, remaining


async def backfill() -> None:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pg, redis)
    try:
        done, remaining = await backfill_with(store)
        if done == 0 and remaining == 0:
            print("nothing to backfill — all resolved decisions already embedded")
        else:
            print(f"backfilled {done}; resolved decisions still null: {remaining}")
    finally:
        await pg.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(backfill())
