"""Projects: table, model, slug, project_id FK (spec 0010 + the no-orphan revision).

Every initiative belongs to a project — there are no orphan specs (project_id is NOT NULL).
a1: a project is created with a name + intent; an initiative is created in it / moved between
projects; the relationship persists. a7: the migration created the "build-doen" project and no
initiative is orphaned. Integration tests over the real docker-compose Postgres + Redis (the
same DB the dev stack + seeds use).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from fastapi.testclient import TestClient
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.exceptions import NotFoundError
from app.models import Decision, Initiative, Project
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


@pytest.fixture
def track_projects():
    """Drop projects created by a test. The FK is ON DELETE RESTRICT, so a project's
    initiatives must go first — delete them, then the project."""
    ids: list[str] = []
    yield ids

    async def drop() -> None:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            for i in ids:
                await c.execute("DELETE FROM initiatives WHERE project_id = $1", i)
                await c.execute("DELETE FROM projects WHERE id = $1", i)
        finally:
            await c.close()

    asyncio.run(drop())


# --- a1: a project is created, an initiative assigned, the link persists ------
def test_create_project_assign_initiative_persists(
    track_initiatives: list[str], track_projects: list[str]
):
    proj = _store_run(
        lambda s: s.create_project("Launch Hosted Tier", "Ship Doen as a hosted SaaS.")
    )
    track_projects.append(proj.id)
    assert isinstance(proj, Project)
    assert proj.id.endswith("-launch-hosted-tier")  # random prefix + name-derived part
    assert proj.name == "Launch Hosted Tier"
    assert proj.intent == "Ship Doen as a hosted SaaS."

    # created directly in the new project — every initiative belongs to a project
    init = _store_run(lambda s: s.create_initiative("Billing Plumbing", proj.id))
    track_initiatives.append(init.id)
    assert init.project_id == proj.id

    # persists across a fresh read, and the project lists the initiative
    got = _store_run(lambda s: s.get_initiative(init.id))
    assert isinstance(got, Initiative) and got.project_id == proj.id
    members = _store_run(lambda s: s.list_project_initiatives(proj.id))
    assert any(m.id == init.id for m in members)

    # creating against an unknown project is rejected (no orphan specs)
    try:
        _store_run(lambda s: s.create_initiative("No Home", "ghost-project"))
        raise AssertionError("expected NotFoundError for an unknown project")
    except NotFoundError:
        pass


# --- a1: same-named projects get distinct slugs via the random prefix ---------
def test_duplicate_project_name_disambiguated(track_projects: list[str]):
    a = _store_run(lambda s: s.create_project("Same Project", "x"))
    b = _store_run(lambda s: s.create_project("Same Project", "y"))
    track_projects.extend([a.id, b.id])
    assert a.id != b.id  # distinct prefixes, no collision
    assert a.id.endswith("-same-project") and b.id.endswith("-same-project")


# --- moving an initiative between projects (there is no detach) ---------------
def test_reassign_initiative_between_projects(
    track_initiatives: list[str], track_projects: list[str]
):
    a = _store_run(lambda s: s.create_project("Group A", ""))
    b = _store_run(lambda s: s.create_project("Group B", ""))
    track_projects.extend([a.id, b.id])
    init = _store_run(lambda s: s.create_initiative("Movable", a.id))
    track_initiatives.append(init.id)
    assert init.project_id == a.id

    moved = _store_run(lambda s: s.assign_initiative_to_project(init.id, b.id))
    assert moved.project_id == b.id  # moved, never orphaned

    # moving to an unknown project is rejected — it can't be left without a home
    try:
        _store_run(lambda s: s.assign_initiative_to_project(init.id, "ghost"))
        raise AssertionError("expected NotFoundError for an unknown project")
    except NotFoundError:
        pass


# --- a7: the migration created build-doen; the schema forbids orphans ---------
def test_no_orphan_specs(track_initiatives: list[str]):
    # build-doen exists with its strategic intent and groups the seeded history (a7).
    proj = _store_run(lambda s: s.get_project("build-doen"))
    assert isinstance(proj, Project)
    assert proj.name == "Build Doen" and proj.intent
    members = _store_run(lambda s: s.list_project_initiatives("build-doen"))
    assert members, "build-doen has no grouped initiatives"

    # the invariant: NO initiative is orphaned — project_id is NOT NULL across the board.
    orphans = _sql("SELECT count(*) AS n FROM initiatives WHERE project_id IS NULL")
    assert orphans["n"] == 0

    # a freshly created initiative lands in a project too (can't be created without one).
    init = _store_run(lambda s: s.create_initiative("Fresh One", "build-doen"))
    track_initiatives.append(init.id)
    assert init.project_id == "build-doen"


# --- existing per-initiative flows still work for a project initiative --------
def test_project_initiative_flows_work(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()  # created under build-doen by the fixture
    got = _store_run(lambda s: s.get_initiative(iid))
    assert got.project_id == "build-doen"

    # spec editing (0002) is unaffected
    r = client.post(
        f"/specs/{iid}/items",
        json={"section": "constraints", "text": "still works", "version": 0},
    )
    assert r.status_code in (200, 201), r.text
    # it shows on the dashboard feed, project_id carried through
    feed = client.get("/initiatives").json()
    entry = next((i for i in feed if i["id"] == iid), None)
    assert entry is not None and entry["project_id"] == "build-doen"


# --- a1: the project CRUD endpoints + assignment over HTTP --------------------
def test_project_endpoints(
    client: TestClient, make_initiative: Callable[[], str], track_projects: list[str]
):
    r = client.post("/projects", json={"name": "API Project", "intent": "via http"})
    assert r.status_code == 201, r.text
    proj = r.json()
    track_projects.append(proj["id"])
    assert proj["id"].endswith("-api-project") and proj["intent"] == "via http"

    # empty name rejected
    assert client.post("/projects", json={"name": "  "}).status_code == 422

    # read it back; it appears in the list
    assert client.get(f"/projects/{proj['id']}").status_code == 200
    assert any(p["id"] == proj["id"] for p in client.get("/projects").json())
    assert client.get("/projects/does-not-exist").status_code == 404

    # assign an initiative over HTTP; the project lists it
    iid = make_initiative()
    a = client.post(f"/initiatives/{iid}/project", json={"project_id": proj["id"]})
    assert a.status_code == 200, a.text
    assert a.json()["project_id"] == proj["id"]
    members = client.get(f"/projects/{proj['id']}/initiatives").json()
    assert any(m["id"] == iid for m in members)

    # assigning to a missing project -> 404
    assert client.post(
        f"/initiatives/{iid}/project", json={"project_id": "ghost"}
    ).status_code == 404


# --- a2: the dashboard bundles project + grouped initiatives + open decisions --
def test_project_dashboard_endpoint(
    client: TestClient, make_initiative: Callable[[], str], track_projects: list[str]
):
    proj = client.post(
        "/projects", json={"name": "Dash Project", "intent": "the strategic goal"}
    ).json()
    track_projects.append(proj["id"])
    iid = make_initiative()
    client.post(f"/initiatives/{iid}/project", json={"project_id": proj["id"]})

    # an open decision in a project initiative shows up in the whole-project aggregate
    _store_run(
        lambda s: s.raise_decision(
            Decision(question="ship it?", options=["yes", "no"]), iid
        )
    )

    r = client.get(f"/projects/{proj['id']}/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["project"]["id"] == proj["id"] and d["project"]["intent"] == "the strategic goal"
    assert any(i["id"] == iid for i in d["initiatives"])  # grouped initiative present
    assert all("stage" in i and "title" in i for i in d["initiatives"])  # nav fields
    assert d["open_decisions"] >= 1  # the escalation is counted project-wide

    assert client.get("/projects/ghost/dashboard").status_code == 404
