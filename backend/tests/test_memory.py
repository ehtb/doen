"""Memory substrate — spec 0005, u1 (a1, a2, a3).

Integration tests against the docker-compose Postgres (migrations run in conftest).
The embedding provider is faked: these criteria are about the *pipeline* (schema,
resolve-time trigger, backfill), not about OpenRouter. Provider quality is judged
live in the a8 HEADLINE. The fake is deterministic and offline — no key needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Callable

import asyncpg
from redis import asyncio as aioredis

from app.backfill_embeddings import backfill_with
from app.config import DATABASE_URL, REDIS_URL
from app.models import Decision
from app.store import SpecStore

DIM = 1536


class FakeEmbedder:
    """Deterministic, offline text->vector. Same text -> same 1536-d vector."""

    dimension = DIM

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


def _run(coro) -> object:
    return asyncio.run(coro)


async def _store(embedder: FakeEmbedder | None = None) -> tuple[SpecStore, asyncpg.Pool, aioredis.Redis]:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return SpecStore(pg, redis, embedder=embedder), pg, redis


def test_pgvector_schema():
    # a1 — extension active, decisions.embedding column, memory table shape.
    async def go():
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            ext = await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            col = await conn.fetchval(
                """SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'decisions' AND column_name = 'embedding'"""
            )
            mem = {
                r["column_name"]
                for r in await conn.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'memory'"
                )
            }
            return ext, col, mem
        finally:
            await conn.close()

    ext, col, mem = _run(go())
    assert ext == 1, "pgvector extension is not active"
    assert col == 1, "decisions.embedding column is missing"
    assert {"id", "initiative_id", "summary", "learnings", "outcome", "embedding", "created_at"} <= mem


def test_resolve_triggers_embedding(make_initiative: Callable[[], str]):
    # a2 — resolving a decision triggers an async embed; the column is populated.
    iid = make_initiative()
    fake = FakeEmbedder()

    async def go():
        store, pg, redis = await _store(fake)
        try:
            d = await store.raise_decision(
                Decision(question="stdio or http for the MCP server?", options=["stdio", "http"]),
                iid,
            )
            await store.resolve_decision(d.id, "stdio", "simplest executor wiring", "edo")
            await store._drain()  # await the fire-and-forget embed
            populated = await pg.fetchval(
                "SELECT embedding IS NOT NULL FROM decisions WHERE id = $1", d.id
            )
            return populated, fake.calls
        finally:
            await pg.close()
            await redis.aclose()

    populated, calls = _run(go())
    assert populated is True, "resolve did not populate the embedding"
    # it embedded the resolved reasoning, not just the question
    assert calls and "Chosen: stdio" in calls[0][0]


def test_backfill_embeds_resolved(make_initiative: Callable[[], str]):
    # a3 — a resolved decision left with a null embedding gets backfilled to non-null.
    iid = make_initiative()
    fake = FakeEmbedder()

    async def go():
        store, pg, redis = await _store(fake)
        try:
            d = await store.raise_decision(
                Decision(question="soft or hard gate to Learn?", options=["soft", "hard"]),
                iid,
            )
            await store.resolve_decision(d.id, "soft", "incomplete work still teaches", "edo")
            await store._drain()
            # simulate a decision resolved before this slice: null out its embedding
            await pg.execute("UPDATE decisions SET embedding = NULL WHERE id = $1", d.id)
            before_null = await pg.fetchval(
                "SELECT embedding IS NULL FROM decisions WHERE id = $1", d.id
            )
            done, remaining = await backfill_with(store, initiative_id=iid)
            after_null = await pg.fetchval(
                "SELECT count(*) FROM decisions WHERE initiative_id = $1 "
                "AND status = 'resolved' AND embedding IS NULL",
                iid,
            )
            return before_null, done, remaining, after_null
        finally:
            await pg.close()
            await redis.aclose()

    before_null, done, remaining, after_null = _run(go())
    assert before_null is True, "setup: embedding should have been nulled"
    assert done >= 1, "backfill embedded nothing"
    assert remaining == 0 and after_null == 0, "a resolved decision is still null after backfill"


# --- u2: Learn stage flow (a4, a5) -------------------------------------------------
async def _raise_resolve(iid: str) -> str:
    """Raise + resolve a decision (with a fake embedder) so a Learn review has reasoning."""
    store, pg, redis = await _store(FakeEmbedder())
    try:
        d = await store.raise_decision(
            Decision(question="soft or hard gate to Learn?", options=["soft", "hard"],
                     recommendation="soft"),
            iid,
        )
        await store.resolve_decision(d.id, "soft", "incomplete work still teaches", "edo")
        await store._drain()
        return d.id
    finally:
        await pg.close()
        await redis.aclose()


def test_create_memory_embeds(make_initiative: Callable[[], str]):
    # a5 (core) — a memory row is created and embedded; list_memory returns it.
    iid = make_initiative()
    fake = FakeEmbedder()

    async def go():
        store, pg, redis = await _store(fake)
        try:
            mem = await store.create_memory(
                iid, "Shipped passwordless sign-in via magic links.",
                learnings="magic links beat passwords for this audience",
            )
            await store._drain()
            populated = await pg.fetchval(
                "SELECT embedding IS NOT NULL FROM memory WHERE id = $1", mem.id
            )
            listed = await store.list_memory(iid)
            return mem.id, populated, [m.id for m in listed], fake.calls
        finally:
            await pg.close()
            await redis.aclose()

    mid, populated, listed_ids, calls = _run(go())
    assert populated is True, "memory row was not embedded"
    assert mid in listed_ids
    assert calls and "Shipped passwordless" in calls[-1][0]


def test_learn_review_and_submit(client, make_initiative: Callable[[], str], monkeypatch):
    # a4 — review shows resolved decisions; a5 — submit records a memory row. The lifecycle
    # state is inferred (0011): with no work units this initiative stays Draft after capture —
    # the all-units-done + learn -> Complete rule is covered in test_initiatives. Embeddings are
    # faked (monkeypatch) so the API path stays offline.
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())
    iid = make_initiative()
    _run(_raise_resolve(iid))

    # a4 — the review carries the resolved decision with its chosen option + rationale
    review = client.get(f"/initiatives/{iid}/learn").json()
    assert "intent" in review
    assert any(
        d["chosen"] == "soft" and "teaches" in (d["rationale"] or "")
        for d in review["decisions"]
    )
    assert review["memory"] == []

    # a5 — submitting an outcome writes a memory row
    r = client.post(
        f"/initiatives/{iid}/learn",
        json={"summary": "Closed out the lifecycle slice.", "learnings": "the loop compounds"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["memory"]) == 1
    assert body["memory"][0]["summary"].startswith("Closed out")

    # constraint 6 — an empty outcome summary is rejected
    assert client.post(f"/initiatives/{iid}/learn", json={"summary": "   "}).status_code == 422


# --- u3: get_context retrieval (a6, a7) --------------------------------------------
def test_get_context_cross_initiative(make_initiative: Callable[[], str]):
    # a7 — get_context returns OTHER initiatives' memory, not just the current one.
    # a6 — each hit is source-attributed with a score. Deterministic via the fake:
    # querying the exact embedded text makes that row distance 0, so it tops the ranking.
    other = make_initiative()
    current = make_initiative()  # the "current" initiative — has no memory of its own
    fake = FakeEmbedder()
    distinctive = "single-use magic-link sign-in that expires after ten minutes"

    async def go():
        store, pg, redis = await _store(fake)
        try:
            # no learnings, so the embedded text equals the summary verbatim
            await store.create_memory(other, distinctive)
            # create_memory alone leaves state='draft' (derive_state([], has_learn=True)=='draft');
            # force complete so the BD-19 filter admits this memory row.
            await pg.execute("UPDATE initiatives SET state = 'complete' WHERE id = $1", other)
            await store._drain()
            hits = await store.get_context(distinctive, limit=5, project_id="build-doen")
            return hits
        finally:
            await pg.close()
            await redis.aclose()

    hits = _run(go())
    assert hits, "get_context returned nothing"
    top = hits[0]
    assert top.type == "memory" and top.initiative_id == other  # retrieved from the OTHER one
    assert top.initiative_id != current
    assert top.text and isinstance(top.score, float)  # source attribution + relevance score
    assert top.score > 0.99  # exact-text match -> ~1.0 similarity


# --- BD-19: get_context only surfaces content from completed initiatives ----------
def test_get_context_excludes_incomplete_initiative(make_initiative: Callable[[], str]):
    # BD-19 item_b54fe02b22d2: high-similarity content from a non-complete initiative
    # must not appear, even when it would otherwise top the ranking.
    draft_id = make_initiative()
    fake = FakeEmbedder()
    distinctive = "provisional-draft-decision-that-must-not-leak-bd19"

    async def go():
        store, pg, redis = await _store(fake)
        try:
            d = await store.raise_decision(
                Decision(question=distinctive, options=["yes", "no"]), draft_id
            )
            await store.resolve_decision(d.id, "yes", "test rationale", "edo")
            await store.embed_decision(d.id)
            await store._drain()
            # state is draft — verify it, then query
            row = await pg.fetchrow("SELECT state FROM initiatives WHERE id = $1", draft_id)
            assert row["state"] == "draft"
            return await store.get_context(distinctive, limit=5, project_id="build-doen")
        finally:
            await pg.close()
            await redis.aclose()

    hits = _run(go())
    assert not any(h.initiative_id == draft_id for h in hits)


def test_get_context_includes_completed_initiative(make_initiative: Callable[[], str]):
    # BD-19 item_130db6160bf9: content from a completed initiative must still appear.
    complete_id = make_initiative()
    fake = FakeEmbedder()
    distinctive = "completed-initiative-memory-that-must-surface-bd19"

    async def go():
        store, pg, redis = await _store(fake)
        try:
            await store.create_memory(complete_id, distinctive)
            await pg.execute("UPDATE initiatives SET state = 'complete' WHERE id = $1", complete_id)
            await store._drain()
            return await store.get_context(distinctive, limit=5, project_id="build-doen")
        finally:
            await pg.close()
            await redis.aclose()

    hits = _run(go())
    assert any(h.initiative_id == complete_id for h in hits)
