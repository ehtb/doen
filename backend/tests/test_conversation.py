"""Conversation: browser-local storage + a stateless backend (spec uvama, u1).

Conversations moved out of Postgres into the browser's IndexedDB (the IndexedDB store + pruning
live in web/lib/conversations.test.ts). What this suite covers on the backend:
  - AC item_ff5a6e8db336: the `messages` table no longer exists in Postgres.
  - AC item_b5be6599f7b3: an Advisor request carries the windowed history in its body and the
    backend persists none of it — no row is written anywhere.
  - constraint 1: assemble_context builds the bounded window from the messages it is GIVEN
    (no store read), plus spec state + relevant memory.

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
from app.models import Message
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


class FakeLLM:
    """A minimal advisor provider: returns a normal conversational turn (no proposals needed)."""

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        return {"reply": "Here's a grounded answer.", "proposals": []}


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


async def _table_counts() -> dict[str, int]:
    """Row counts for every base table in the public schema — to assert nothing was persisted."""
    c = await asyncpg.connect(DATABASE_URL)
    try:
        names = [
            r["tablename"]
            for r in await c.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        ]
        counts: dict[str, int] = {}
        for n in names:
            counts[n] = await c.fetchval(f'SELECT count(*) FROM "{n}"')
        return counts
    finally:
        await c.close()


# --- AC item_ff5a6e8db336: the messages table is gone from Postgres ------------------
def test_messages_table_dropped():
    async def go() -> bool:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            return await c.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename = 'messages')"
            )
        finally:
            await c.close()

    assert asyncio.run(go()) is False, "the messages table should no longer exist"


# --- AC item_b5be6599f7b3: an Advisor request persists nothing -----------------------
def test_advisor_request_persists_nothing(
    client: TestClient, make_initiative: Callable[[], str], monkeypatch
):
    monkeypatch.setattr("app.services.advisor.get_advisor_llm", lambda: FakeLLM())
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())
    iid = make_initiative()

    before = asyncio.run(_table_counts())
    # a fabricated windowed history rides along in the request body
    r = client.post(
        f"/initiatives/{iid}/advisor",
        json={
            "content": "given what we discussed, what next?",
            "history": [
                {"role": "human", "content": "let's talk about the export"},
                {"role": "advisor", "content": "sure — streaming or buffered?"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["message"]["role"] == "advisor"  # a reply was generated

    after = asyncio.run(_table_counts())
    assert after == before, f"the Advisor call wrote rows: { {k: (before.get(k), after[k]) for k in after if after[k] != before.get(k)} }"


# --- constraint 1: assemble_context uses the GIVEN window (no store read) -------------
def test_assemble_context_uses_given_window(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    window = [Message(initiative_id=iid, role="human", content=f"m{i}") for i in range(5)]

    def build(store: SpecStore):
        return assemble_context(store, iid, messages=window, memory_limit=3)

    ctx = _store_run(build, embedder=FakeEmbedder())
    assert [m.content for m in ctx.messages] == ["m0", "m1", "m2", "m3", "m4"]  # exactly what we gave
    assert ctx.spec is not None and ctx.spec.initiative_id == iid  # spec state is included


# --- constraint 1: relevant memory is retrieved against the latest human turn --------
def test_context_includes_relevant_memory(
    client: TestClient, make_initiative: Callable[[], str]
):
    other = make_initiative()    # carries a memory row
    current = make_initiative()  # the active conversation; no memory of its own
    distinctive = "single-use magic-link sign-in that expires after ten minutes"

    def build(store: SpecStore):
        async def go():
            await store.create_memory(other, distinctive)  # embedded text == summary verbatim
            await store.pg.execute("UPDATE initiatives SET state = 'complete' WHERE id = $1", other)
            await store._drain()
            window = [Message(initiative_id=current, role="human", content=distinctive)]
            return await assemble_context(store, current, messages=window, memory_limit=5)

        return go()

    ctx = _store_run(build, embedder=FakeEmbedder())
    assert ctx.memory, "assembled context retrieved no memory"
    top = ctx.memory[0]
    assert top.initiative_id == other and top.type == "memory"  # cross-initiative recall
    assert top.score > 0.99  # exact-text match -> ~1.0 similarity


# --- the empty-content guard still rejects a blank turn ------------------------------
def test_advisor_rejects_blank_content(
    client: TestClient, make_initiative: Callable[[], str], monkeypatch
):
    monkeypatch.setattr("app.services.advisor.get_advisor_llm", lambda: FakeLLM())
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())
    iid = make_initiative()
    r = client.post(f"/initiatives/{iid}/advisor", json={"content": "   ", "history": []})
    assert r.status_code == 422
    # an unknown initiative is a 404
    assert client.post("/initiatives/nope/advisor", json={"content": "hi", "history": []}).status_code == 404
