"""u1 — conversation persistence (spec 0009).

Covers a4 (history persists across sessions; messages are individual rows with role,
content, timestamp) and constraint 1 (the Advisor's context is an explicit bounded
window: recent messages + spec state + relevant memory). The LLM is NOT exercised here —
u1 is storage + retrieval + context assembly; the Advisor's reply generation is u2.
Integration tests over the real docker-compose Postgres + Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from fastapi.testclient import TestClient
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.main import app
from app.services.conversation import assemble_context
from app.store import SpecStore

DIM = 1536


class FakeEmbedder:
    """Deterministic, offline text->vector — same text yields the same 1536-d vector, so an
    exact-text query lands distance ~0. Keeps the memory-assembly test offline (no key)."""

    dimension = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


def _store_run(
    fn: Callable[[SpecStore], Awaitable[object]], embedder: FakeEmbedder | None = None
) -> object:
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis, embedder=embedder))
        finally:
            await pg.close()
            await redis.aclose()

    return asyncio.run(go())


def _message_rows(iid: str) -> list[asyncpg.Record]:
    async def go() -> list[asyncpg.Record]:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            return await c.fetch(
                "SELECT role, content, created_at FROM messages "
                "WHERE initiative_id = $1 ORDER BY seq",
                iid,
            )
        finally:
            await c.close()

    return asyncio.run(go())


# --- a4: a posted turn persists and replays on a fresh session ----------------
def test_messages_persist_across_sessions(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    r = client.post(f"/initiatives/{iid}/messages", json={"content": "What should I build first?"})
    assert r.status_code == 201, r.text
    posted = r.json()
    assert posted["role"] == "human"
    assert posted["content"] == "What should I build first?"
    assert posted["created_at"]  # the rail renders a timestamp

    # a second TestClient runs a fresh lifespan (new pool) — a genuine reopen. The history
    # comes back from Postgres, not from any in-process state.
    with TestClient(app) as reopened:
        got = reopened.get(f"/initiatives/{iid}/messages").json()
    assert [m["content"] for m in got] == ["What should I build first?"]
    assert got[0]["id"] == posted["id"]


# --- a4: messages are individual rows with role, content, timestamp -----------
def test_messages_are_individual_rows(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    for text in ["first", "second", "third"]:
        assert client.post(f"/initiatives/{iid}/messages", json={"content": text}).status_code == 201

    rows = _message_rows(iid)
    assert [r["content"] for r in rows] == ["first", "second", "third"]  # insertion order
    assert all(r["role"] == "human" for r in rows)
    assert all(r["created_at"] is not None for r in rows)  # a real timestamp column


# --- a4 (u2 substrate): an Advisor turn round-trips with its metadata ----------
def test_advisor_message_metadata_roundtrips(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    card = {"proposals": [{"section": "constraints", "text": "must be idempotent"}]}

    def append_both(store: SpecStore):
        async def go():
            await store.append_message(iid, "human", "shape this")
            await store.append_message(iid, "advisor", "Here's a proposal.", metadata=card)
            return await store.list_messages(iid)

        return go()

    msgs = _store_run(append_both)
    assert [m.role for m in msgs] == ["human", "advisor"]  # oldest-first
    assert msgs[1].metadata == card  # JSONB payload survives the round-trip


def test_post_message_validation(client: TestClient, make_initiative: Callable[[], str]):
    iid = make_initiative()
    # empty content is rejected (and nothing lands)
    assert client.post(f"/initiatives/{iid}/messages", json={"content": "   "}).status_code == 422
    # posting to an unknown initiative is a 404
    assert client.post("/initiatives/nope/messages", json={"content": "hi"}).status_code == 404
    assert _message_rows(iid) == []


# --- constraint 1: the assembled context is a bounded recent window -----------
def test_context_window_bounds_messages(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()

    def build(store: SpecStore):
        async def go():
            for i in range(12):
                await store.append_message(iid, "human", f"m{i}")
            return await assemble_context(store, iid, window=5, memory_limit=3)

        return go()

    ctx = _store_run(build, embedder=FakeEmbedder())
    assert [m.content for m in ctx.messages] == ["m7", "m8", "m9", "m10", "m11"]  # last 5, in order
    assert ctx.spec is not None and ctx.spec.initiative_id == iid  # spec state is included


# --- constraint 1: relevant memory is retrieved against the latest human turn --
def test_context_includes_relevant_memory(
    client: TestClient, make_initiative: Callable[[], str]
):
    other = make_initiative()    # carries a memory row
    current = make_initiative()  # the active conversation; no memory of its own
    distinctive = "single-use magic-link sign-in that expires after ten minutes"

    def build(store: SpecStore):
        async def go():
            await store.create_memory(other, distinctive)  # embedded text == summary verbatim
            await store._drain()
            await store.append_message(current, "human", distinctive)  # anchors the memory query
            return await assemble_context(store, current, memory_limit=5)

        return go()

    ctx = _store_run(build, embedder=FakeEmbedder())
    assert ctx.memory, "assembled context retrieved no memory"
    top = ctx.memory[0]
    assert top.initiative_id == other and top.type == "memory"  # cross-initiative recall
    assert top.score > 0.99  # exact-text match -> ~1.0 similarity
