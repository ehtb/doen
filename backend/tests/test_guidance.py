"""u4 — get_guidance: the Advisor's per-unit briefing (spec 0009, a6).

The briefing is grounded (constraints, criteria, memory pulled from the spec + corpus) plus
an Advisor synthesis (briefing + pitfalls, faked here). Covers a6 (a unit-scoped briefing
informed by spec + memory) and the caching/invalidation behaviour (constraint 5 / discretion).
Integration tests need docker-compose Postgres + Redis. The LLM + embedder are faked offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.exceptions import NotFoundError
from app.models import AcceptanceCriterion, SpecItem, Verify, WorkUnit
from app.services.guidance import generate_guidance
from app.store import SpecStore

DIM = 1536

GUIDANCE_PAYLOAD = {
    "briefing": "Lean on the O(1) constraint — evaluate from an in-memory snapshot, refreshed "
    "out of band. The 1s-propagation criterion is the load-bearing one.",
    "pitfalls": [
        "Don't call the flag store on the hot path — that breaks the O(1) constraint.",
        "A stale snapshot can blow the 1s propagation criterion.",
    ],
}


class FakeLLM:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or GUIDANCE_PAYLOAD
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        return self.payload


class FakeEmbedder:
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


async def _seed_unit(store: SpecStore, iid: str) -> tuple[str, str]:
    """Confirm a constraint + an acceptance criterion, then create a unit mapping to it."""
    spec = await store.get_spec(iid)
    assert spec is not None
    spec.constraints.append(
        SpecItem(text="Flag checks must be O(1) and never hit the network.",
                 provenance="human", status="confirmed")
    )
    crit = AcceptanceCriterion(
        text="A flag flip takes effect within 1s.",
        verify=Verify(kind="test", detail="flip a flag; assert propagation < 1s"),
        provenance="human", status="confirmed",
    )
    spec.acceptance.append(crit)
    await store.save_spec(spec)  # -> v1
    unit = await store.create_unit(
        WorkUnit(spec_id=iid, title="evaluation core", scope="the in-memory flag evaluator",
                 criterion_ids=[crit.id])
    )
    return unit.id, crit.id


# --- a6: the briefing is grounded in the spec + synthesised by the Advisor ----
def test_guidance_is_grounded_and_synthesised(make_initiative: Callable[[], str]):
    iid = make_initiative()
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            unit_id, _ = await _seed_unit(store, iid)
            return await generate_guidance(store, unit_id, llm=fake)

        return inner()

    g = _store_run(go, embedder=FakeEmbedder())
    assert g.title == "evaluation core" and g.scope == "the in-memory flag evaluator"
    assert g.spec_version == 1
    # grounded straight from the spec — not invented by the LLM
    assert g.constraints == ["Flag checks must be O(1) and never hit the network."]
    assert any("flip takes effect within 1s" in c and "verify: test" in c for c in g.criteria)
    # synthesised by the Advisor
    assert g.briefing == GUIDANCE_PAYLOAD["briefing"]
    assert g.pitfalls == GUIDANCE_PAYLOAD["pitfalls"]
    # the binding constraints + criteria were fed to the LLM (a6 awareness)
    assert "O(1)" in fake.calls[0]["user"] and "flip takes effect within 1s" in fake.calls[0]["user"]
    assert fake.calls[0]["schema_name"] == "guidance"


# --- constraint 5 / discretion: cached by unit + spec version, invalidated on edit
def test_guidance_cached_until_spec_changes(make_initiative: Callable[[], str]):
    iid = make_initiative()
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            unit_id, _ = await _seed_unit(store, iid)  # spec at v1
            await generate_guidance(store, unit_id, llm=fake)  # generates + caches
            await generate_guidance(store, unit_id, llm=fake)  # served from cache
            calls_after_cache_hit = len(fake.calls)
            # a spec edit bumps the version -> the old briefing's key is never read again
            spec = await store.get_spec(iid)
            assert spec is not None
            spec.discretion.append(
                SpecItem(text="snapshot refresh cadence is yours", provenance="human", status="confirmed")
            )
            await store.save_spec(spec)  # -> v2
            regen = await generate_guidance(store, unit_id, llm=fake)  # cache miss -> regenerate
            return calls_after_cache_hit, len(fake.calls), regen.spec_version

        return inner()

    after_hit, after_regen, version = _store_run(go, embedder=FakeEmbedder())
    assert after_hit == 1, "the second call should have been served from cache"
    assert after_regen == 2, "a spec edit should invalidate the cached briefing"
    assert version == 2


# --- a6: prior patterns are retrieved into the briefing -----------------------
def test_guidance_includes_relevant_memory(make_initiative: Callable[[], str]):
    other = make_initiative()
    iid = make_initiative()
    distinctive = "the in-memory flag evaluator"  # equals the unit scope -> exact-match recall
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            await store.create_memory(other, distinctive)
            await store.pg.execute("UPDATE initiatives SET state = 'complete' WHERE id = $1", other)
            await store._drain()
            unit_id, _ = await _seed_unit(store, iid)
            return await generate_guidance(store, unit_id, llm=fake)

        return inner()

    g = _store_run(go, embedder=FakeEmbedder())
    assert g.memory, "no prior patterns retrieved into the briefing"
    # cross-initiative recall: the prior pattern comes from the OTHER initiative, attributed
    # and scored (the ranking itself is exercised in test_memory).
    assert g.memory[0].initiative_id == other and isinstance(g.memory[0].score, float)


# --- unknown unit -> a clean not-found (the MCP tool maps this to a tool error)
def test_guidance_unknown_unit_raises(make_initiative: Callable[[], str]):
    def go(store: SpecStore):
        async def inner():
            try:
                await generate_guidance(store, "unit_does_not_exist", llm=FakeLLM())
                return "no-error"
            except NotFoundError:
                return "not-found"

        return inner()

    assert _store_run(go, embedder=FakeEmbedder()) == "not-found"
