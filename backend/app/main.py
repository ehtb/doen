"""Doen backend entrypoint.

u1 scope: scaffold + lifespan wiring only. The lifespan owns one shared asyncpg
pool and one redis client; SpecStore is constructed per-request over them via the
`store` dependency. Routes and migrations arrive in u2.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Postgres is the source of truth; Redis is the derived hot cache. One pool,
    # one client, shared for the process lifetime.
    app.state.pg = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    await app.state.redis.ping()  # from_url is lazy — ping so a dead Redis fails boot
    try:
        yield
    finally:
        await app.state.pg.close()
        await app.state.redis.aclose()


app = FastAPI(title="Doen", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health(request: Request) -> dict:
    pg_ok = await request.app.state.pg.fetchval("SELECT 1") == 1
    redis_ok = bool(await request.app.state.redis.ping())
    return {"status": "ok" if pg_ok and redis_ok else "degraded",
            "postgres": pg_ok, "redis": redis_ok}
