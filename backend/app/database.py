"""Shared datastore resources + the FastAPI dependencies over them.

The lifespan owns exactly one asyncpg pool and one Redis client for the process; routers
get a per-request SpecStore over them via the `get_store` dependency. Postgres is the
source of truth; Redis handles real-time coordination (decision pub/sub, escalation stream).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.store import SpecStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pg = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    await app.state.redis.ping()  # type: ignore  # redis.asyncio ping is awaitable; stubs mistype it
    try:
        yield
    finally:
        await app.state.pg.close()
        await app.state.redis.aclose()


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pg


def get_store(request: Request) -> SpecStore:
    """Per-request SpecStore over the shared pool + Redis client."""
    return SpecStore(request.app.state.pg, request.app.state.redis)
