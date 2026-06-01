"""Initiatives as the parent entity: table, model, ID format, scaffolded spec, lifecycle state.

Covers create (persists an initiative row + scaffolds an empty v0 spec at state=draft), the
{prefix}-{seq} ID format (avhle u1: server-assigned, race-safe, client-supplied ID ignored),
and the 0011 lifecycle: a1 (three states; the migration maps the old stages correctly) and a2
(state is inferred from the work units + learn record, with no manual advance).
get_initiative surfaces the {id, title, state} the MCP get_spec response carries.
Integration tests over the real docker-compose Postgres + Redis.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor

import asyncpg
import pytest
from fastapi.testclient import TestClient
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.models import (
    CriterionResult,
    Initiative,
    Submission,
    WorkUnit,
    derive_state,
    slugify,
)
from app.store import SpecStore


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


# --- pure slugify helper (still used by project creation) ----------------------
def test_slugify_kebab_cases_the_title():
    assert slugify("Passwordless Sign-In") == "passwordless-sign-in"
    assert slugify("  Spaces & Symbols!! ") == "spaces-symbols"
    assert slugify("") == "initiative"


# --- avhle u1 / item_f70eeff560a4: ID is {prefix}-{seq}, server-assigned ------
def test_create_initiative_returns_prefix_seq_id(track_initiatives: list[str]):
    """Creating two initiatives yields BD-N and BD-(N+1); IDs have no random suffix."""
    a = _store_run(lambda s: s.create_initiative("Alpha", "build-doen"))
    b = _store_run(lambda s: s.create_initiative("Beta", "build-doen"))
    track_initiatives.extend([a.id, b.id])
    assert re.fullmatch(r"BD-\d+", a.id), f"unexpected id: {a.id}"
    assert re.fullmatch(r"BD-\d+", b.id), f"unexpected id: {b.id}"
    assert b.seq == a.seq + 1  # contiguous per-project


# --- avhle u1 / item_f70eeff560a4: client-supplied id is ignored ---------------
def test_create_initiative_endpoint_ignores_client_id(
    client: TestClient, track_initiatives: list[str]
):
    """Sending an 'id' field in the payload must not affect the server-assigned ID."""
    r = client.post(
        "/initiatives",
        json={"title": "Client ID Test", "project_id": "build-doen", "id": "should-be-ignored"},
    )
    assert r.status_code == 201, r.text
    init = r.json()
    track_initiatives.append(init["id"])
    assert re.fullmatch(r"BD-\d+", init["id"]), f"id not in prefix-seq format: {init['id']}"
    assert init["id"] != "should-be-ignored"


# --- avhle u1 / item_45ac98eca08d: seq is race-safe ----------------------------
def test_create_initiative_seq_race_safe(track_initiatives: list[str]):
    """N concurrent creations in the same project must produce N distinct seq values."""
    n = 8

    def _create(_: int) -> Initiative:
        return _store_run(lambda s: s.create_initiative(f"Concurrent {_}", "build-doen"))

    with ThreadPoolExecutor(max_workers=n) as pool:
        initiatives = list(pool.map(_create, range(n)))

    for init in initiatives:
        track_initiatives.append(init.id)

    seqs = [i.seq for i in initiatives]
    assert len(seqs) == len(set(seqs)), f"duplicate seq values: {seqs}"
    ids = [i.id for i in initiatives]
    assert len(ids) == len(set(ids)), f"duplicate IDs: {ids}"
    for iid in ids:
        assert re.fullmatch(r"BD-\d+", iid), f"unexpected id format: {iid}"


# --- create persists an initiative + scaffolds an empty v0/draft spec ----------
def test_create_initiative_scaffolds_empty_spec(track_initiatives: list[str]):
    init = _store_run(lambda s: s.create_initiative("Passwordless Sign-In", "build-doen"))
    track_initiatives.append(init.id)
    assert re.fullmatch(r"BD-\d+", init.id), f"unexpected id: {init.id}"
    assert init.title == "Passwordless Sign-In"
    assert init.state == "draft"  # nothing under construction yet (0011)

    row = _sql("SELECT title, state FROM initiatives WHERE id = $1", init.id)
    assert row["title"] == "Passwordless Sign-In"
    assert row["state"] == "draft"

    spec = _store_run(lambda s: s.get_spec(init.id))
    assert spec is not None
    assert spec.version == 0
    assert spec.state == "draft"
    assert spec.title == "Passwordless Sign-In"
    assert spec.constraints == [] and spec.discretion == [] and spec.acceptance == []


# --- same-titled initiatives still get distinct IDs (distinct seq) -------------
def test_duplicate_title_has_distinct_ids(track_initiatives: list[str]):
    a = _store_run(lambda s: s.create_initiative("Same Title", "build-doen"))
    b = _store_run(lambda s: s.create_initiative("Same Title", "build-doen"))
    track_initiatives.extend([a.id, b.id])
    assert a.id != b.id


# --- D1 fold-in: get_initiative surfaces the lifecycle metadata ----------------
def test_get_initiative_returns_lifecycle_metadata(track_initiatives: list[str]):
    init = _store_run(lambda s: s.create_initiative("Lifecycle Meta", "build-doen"))
    track_initiatives.append(init.id)
    got = _store_run(lambda s: s.get_initiative(init.id))
    assert isinstance(got, Initiative)
    assert got.id == init.id
    assert re.fullmatch(r"BD-\d+", got.id), f"unexpected id: {got.id}"
    assert (got.title, got.state) == ("Lifecycle Meta", "draft")
    assert _store_run(lambda s: s.get_initiative("does-not-exist")) is None


# --- a1: three states; the migration mapped the old 7-stage data correctly -----
def test_lifecycle_has_three_states_and_migration_mapped():
    # the 7-stage model is replaced: every initiative carries one of exactly three states.
    rows = _sql("SELECT array_agg(DISTINCT state) AS states FROM initiatives")
    assert set(rows["states"]) <= {"draft", "building", "complete"}
    assert _sql("SELECT count(*) AS n FROM initiatives WHERE state IS NULL")["n"] == 0

    # the migration maps the old stages: a learn-era initiative became Complete (learn ->
    # complete), a shaping-era one stayed Draft (discover/shape/bet/decompose -> draft).
    learn_era = _sql(
        "SELECT state FROM initiatives WHERE id = 'build-doen-0005-memory-learn-stage'"
    )
    assert learn_era["state"] == "complete"
    shaping_era = _sql(
        "SELECT state FROM initiatives WHERE id = 'build-doen-0002-spec-editing'"
    )
    assert shaping_era["state"] == "draft"


# --- a1/a2: the inferred-state rule is pure (no DB) -----------------------------
def test_derive_state_rule():
    assert derive_state([], False) == "draft"               # nothing yet
    assert derive_state(["proposed", "ready"], False) == "draft"   # not started
    assert derive_state(["in_progress"], False) == "building"
    assert derive_state(["blocked_on_decision"], False) == "building"
    assert derive_state(["done", "ready"], False) == "building"    # some built, not all done
    assert derive_state(["done"], False) == "building"             # done but no learnings
    assert derive_state(["done", "done"], True) == "complete"      # all done + learn
    assert derive_state([], True) == "draft"                       # learn alone doesn't complete


# --- the dashboard feed lists spec-bearing initiatives with title + state ------
def test_list_initiatives_includes_created_one(
    client: TestClient, track_initiatives: list[str]
):
    init = _store_run(lambda s: s.create_initiative("Dashboard Listing", "build-doen"))
    track_initiatives.append(init.id)

    r = client.get("/initiatives")
    assert r.status_code == 200, r.text
    items = r.json()
    found = next((i for i in items if i["id"] == init.id), None)
    assert found is not None  # the new initiative appears on the dashboard feed
    assert found["title"] == "Dashboard Listing"
    assert found["state"] == "draft"
    # every entry carries what the dashboard renders + links on
    assert all(i["id"] and "state" in i for i in items)


# --- a1 / a7: the create endpoint scaffolds an initiative + spec in one act -----
def test_create_initiative_endpoint_scaffolds(
    client: TestClient, track_initiatives: list[str]
):
    r = client.post("/initiatives", json={"title": "Endpoint Made", "project_id": "build-doen"})
    assert r.status_code == 201, r.text
    init = r.json()
    track_initiatives.append(init["id"])
    assert re.fullmatch(r"BD-\d+", init["id"]), f"unexpected id: {init['id']}"
    assert init["state"] == "draft"
    assert init["project_id"] == "build-doen"  # every initiative belongs to a project

    # land straight in the empty spec (a7) — readable immediately, v0/draft, empty
    g = client.get(f"/specs/{init['id']}")
    assert g.status_code == 200, g.text
    spec = g.json()
    assert spec["version"] == 0 and spec["state"] == "draft"
    assert spec["constraints"] == [] and spec["acceptance"] == []

    # an empty title is rejected
    assert client.post(
        "/initiatives", json={"title": "   ", "project_id": "build-doen"}
    ).status_code == 422
    # a missing/unknown project is rejected too (no orphan specs)
    assert client.post("/initiatives", json={"title": "Needs A Home"}).status_code == 422
    assert client.post(
        "/initiatives", json={"title": "Ghost Project", "project_id": "nope"}
    ).status_code == 404


# --- a2: state is inferred from the units + learn; no manual advance ------------
def test_state_inferred_from_units_and_learn(
    client: TestClient, track_initiatives: list[str]
):
    init = _store_run(lambda s: s.create_initiative("Auto State", "build-doen"))
    track_initiatives.append(init.id)

    def state() -> str:
        got = _store_run(lambda s: s.get_initiative(init.id))
        assert isinstance(got, Initiative)
        return got.state

    # no manual advance endpoint exists any more (the lifecycle is inferred)
    assert client.post(f"/initiatives/{init.id}/stage", json={"stage": "shape"}).status_code == 404

    # draft: no units yet, and a proposed/ready unit hasn't started the work
    assert state() == "draft"
    unit = WorkUnit(spec_id=init.id, title="ship it", scope="the whole thing")
    _store_run(lambda s: s.create_unit(unit))
    assert state() == "draft"
    _store_run(lambda s: s.confirm_unit(unit.id))  # proposed -> ready
    assert state() == "draft"

    # building: the first unit reaching in_progress flips it
    _store_run(lambda s: s.claim_unit(unit.id))  # ready -> in_progress
    assert state() == "building"
    assert client.get(f"/specs/{init.id}").json()["state"] == "building"  # mirrored onto the doc

    # still building while the unit is in verification, and even once approved (no learn yet)
    sub = Submission(
        summary="done", criteria_results=[CriterionResult(criterion_id="c1", result="pass")]
    )
    _store_run(lambda s: s.submit_for_verification(unit.id, sub))
    assert state() == "building"
    _store_run(lambda s: s.record_verdict(unit.id, "approved", "", "tester"))  # -> done
    assert state() == "building"

    # complete: every unit done AND a learn record captured
    _store_run(lambda s: s.create_memory(init.id, "shipped passwordless sign-in"))
    assert state() == "complete"
    assert client.get(f"/specs/{init.id}").json()["state"] == "complete"
