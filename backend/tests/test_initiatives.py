"""u1 — initiatives as the parent entity: table, model, slug, scaffolded spec, migration.

Covers a1 (create persists an initiative row + scaffolds an empty v0 spec), a2 (slug
derived from the title, unique, duplicate disambiguated), a6 (the lifecycle migration
backfills title + stage from each spec). Also the D1 fold-in: get_initiative surfaces the
{id, title, stage} that the MCP get_spec response now carries. Integration tests over the
real docker-compose Postgres + Redis.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.store import Initiative, SpecStore, slugify

MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "0003_initiative_lifecycle.sql"
)


def _store_run(fn: Callable[[SpecStore], Awaitable[object]]) -> object:
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis))
        finally:
            await pg.close()
            await redis.aclose()

    return asyncio.run(go())


def _sql(query: str, *args: object) -> object:
    async def go() -> object:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            if query.lstrip().upper().startswith("SELECT"):
                return await c.fetchrow(query, *args)
            return await c.execute(query, *args)
        finally:
            await c.close()

    return asyncio.run(go())


@pytest.fixture
def track_initiatives():
    """Drop initiatives created directly via the store (cascade removes their specs)."""
    ids: list[str] = []
    yield ids

    async def drop() -> None:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            for i in ids:
                await c.execute("DELETE FROM initiatives WHERE id = $1", i)
        finally:
            await c.close()

    asyncio.run(drop())


# --- a2: slug derivation (pure) -----------------------------------------------
def test_slugify_kebab_cases_the_title():
    assert slugify("Passwordless Sign-In") == "passwordless-sign-in"
    assert slugify("  Spaces & Symbols!! ") == "spaces-symbols"
    assert slugify("") == "initiative"


# --- a1: create persists an initiative + scaffolds an empty v0/discover spec ---
def test_create_initiative_scaffolds_empty_spec(track_initiatives: list[str]):
    init = _store_run(lambda s: s.create_initiative("Passwordless Sign-In"))
    track_initiatives.append(init.id)
    assert init.id == "passwordless-sign-in"
    assert init.title == "Passwordless Sign-In"
    assert init.stage == "discover"

    row = _sql("SELECT title, stage FROM initiatives WHERE id = $1", init.id)
    assert row["title"] == "Passwordless Sign-In"
    assert row["stage"] == "discover"

    spec = _store_run(lambda s: s.get_spec(init.id))
    assert spec is not None
    assert spec.version == 0
    assert spec.stage == "discover"
    assert spec.title == "Passwordless Sign-In"
    assert spec.constraints == [] and spec.discretion == [] and spec.acceptance == []


# --- a2: duplicate titles disambiguate to distinct unique slugs (no error) -----
def test_duplicate_title_disambiguated(track_initiatives: list[str]):
    a = _store_run(lambda s: s.create_initiative("Same Title"))
    b = _store_run(lambda s: s.create_initiative("Same Title"))
    track_initiatives.extend([a.id, b.id])
    assert a.id == "same-title"
    assert b.id == "same-title-2"


# --- D1 fold-in: get_initiative surfaces the lifecycle metadata ----------------
def test_get_initiative_returns_lifecycle_metadata(track_initiatives: list[str]):
    init = _store_run(lambda s: s.create_initiative("Lifecycle Meta"))
    track_initiatives.append(init.id)
    got = _store_run(lambda s: s.get_initiative(init.id))
    assert isinstance(got, Initiative)
    assert (got.id, got.title, got.stage) == ("lifecycle-meta", "Lifecycle Meta", "discover")
    assert _store_run(lambda s: s.get_initiative("does-not-exist")) is None


# --- a6: the migration backfills title + stage from the spec -------------------
def test_migration_backfills_title_and_stage(
    client: TestClient, make_initiative: Callable[[], str], track_initiatives: list[str]
):
    iid = make_initiative()  # created via the legacy endpoint: no title
    track_initiatives.append(iid)
    r = client.put(
        f"/specs/{iid}",
        json={"initiative_id": iid, "title": "Backfill Me", "version": 0, "stage": "bet"},
    )
    assert r.status_code == 200, r.text

    # simulate the pre-0004 state, then re-run the (idempotent) migration SQL
    _sql("UPDATE initiatives SET title = NULL, stage = 'shape' WHERE id = $1", iid)
    _sql(MIGRATION.read_text())

    row = _sql("SELECT title, stage FROM initiatives WHERE id = $1", iid)
    assert row["title"] == "Backfill Me"  # filled from the spec
    assert row["stage"] == "bet"          # synced from the spec


# --- a3: the dashboard feed lists spec-bearing initiatives with title + stage --
def test_list_initiatives_includes_created_one(
    client: TestClient, track_initiatives: list[str]
):
    init = _store_run(lambda s: s.create_initiative("Dashboard Listing"))
    track_initiatives.append(init.id)

    r = client.get("/initiatives")
    assert r.status_code == 200, r.text
    items = r.json()
    found = next((i for i in items if i["id"] == init.id), None)
    assert found is not None  # the new initiative appears on the dashboard feed
    assert found["title"] == "Dashboard Listing"
    assert found["stage"] == "discover"
    # every entry carries what the dashboard renders + links on
    assert all(i["id"] and "stage" in i for i in items)


# --- a1 / a7: the create endpoint scaffolds an initiative + spec in one act -----
def test_create_initiative_endpoint_scaffolds(
    client: TestClient, track_initiatives: list[str]
):
    r = client.post("/initiatives", json={"title": "Endpoint Made"})
    assert r.status_code == 201, r.text
    init = r.json()
    track_initiatives.append(init["id"])
    assert init["id"] == "endpoint-made"
    assert init["stage"] == "discover"

    # land straight in the empty spec (a7) — readable immediately, v0/discover, empty
    g = client.get(f"/specs/{init['id']}")
    assert g.status_code == 200, g.text
    spec = g.json()
    assert spec["version"] == 0 and spec["stage"] == "discover"
    assert spec["constraints"] == [] and spec["acceptance"] == []

    # an empty title is rejected
    assert client.post("/initiatives", json={"title": "   "}).status_code == 422


# --- a5: advance/retreat one step; the spec's stage stays in sync --------------
def test_stage_advance_and_retreat_sync_spec(
    client: TestClient, track_initiatives: list[str]
):
    init = _store_run(lambda s: s.create_initiative("Stage Sync"))
    track_initiatives.append(init.id)

    r = client.post(f"/initiatives/{init.id}/stage", json={"stage": "shape"})  # discover -> shape
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "shape"
    assert client.get(f"/specs/{init.id}").json()["stage"] == "shape"  # spec synced

    r = client.post(f"/initiatives/{init.id}/stage", json={"stage": "discover"})  # retreat
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "discover"
    assert client.get(f"/specs/{init.id}").json()["stage"] == "discover"


# --- a4: skips and arbitrary jumps are rejected; nothing moves -----------------
def test_stage_rejects_skips(client: TestClient, track_initiatives: list[str]):
    init = _store_run(lambda s: s.create_initiative("Stage Skip"))
    track_initiatives.append(init.id)

    # discover -> implement skips four stages -> 422
    assert client.post(
        f"/initiatives/{init.id}/stage", json={"stage": "implement"}
    ).status_code == 422
    # unknown initiative -> 404
    assert client.post("/initiatives/nope/stage", json={"stage": "shape"}).status_code == 404
    # the rejected jump left the stage untouched
    assert client.get(f"/specs/{init.id}").json()["stage"] == "discover"
