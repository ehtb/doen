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
from app.exceptions import NotFoundError, ValidationError
from app.models import Decision, Initiative, Project, slugify
from app.store import SpecStore


def _store_run(fn: Callable[[SpecStore], Awaitable[object]]) -> object:
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis))
        finally:
            await pg.close()
            await redis.close()

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
    assert proj.id == slugify("Launch Hosted Tier")  # BD-11: ID is the full name slug
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


# --- BD-11: duplicate project names are rejected (name uniqueness enforced) ----
def test_duplicate_project_name_rejected(track_projects: list[str]):
    a = _store_run(lambda s: s.create_project("Same Project", "x"))
    track_projects.append(a.id)
    assert a.id == "same-project"
    try:
        b = _store_run(lambda s: s.create_project("Same Project", "y"))
        track_projects.append(b.id)
        raise AssertionError("expected ValidationError for duplicate name")
    except ValidationError:
        pass


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


# --- a7: the schema forbids orphans ------------------------------------------
def test_no_orphan_specs(track_initiatives: list[str], track_projects: list[str]):
    proj = _store_run(lambda s: s.create_project("Orphan Test", "no-orphan invariant test"))
    track_projects.append(proj.id)

    # the invariant: NO initiative is orphaned — project_id is NOT NULL across the board.
    orphans = _sql("SELECT count(*) AS n FROM initiatives WHERE project_id IS NULL")
    assert orphans["n"] == 0

    # a freshly created initiative lands in a project (can't be created without one).
    init = _store_run(lambda s: s.create_initiative("Fresh One", proj.id))
    track_initiatives.append(init.id)
    assert init.project_id == proj.id


# --- existing per-initiative flows still work for a project initiative --------
def test_project_initiative_flows_work(
    client: TestClient, make_initiative: Callable[[], str], project: str
):
    iid = make_initiative()
    got = _store_run(lambda s: s.get_initiative(iid))
    assert got.project_id == project

    # spec editing (0002) is unaffected
    r = client.post(
        f"/specs/{iid}/items",
        json={"section": "constraints", "text": "still works", "version": 0},
    )
    assert r.status_code in (200, 201), r.text
    # it shows on the dashboard feed, project_id carried through
    feed = client.get("/initiatives").json()
    entry = next((i for i in feed if i["id"] == iid), None)
    assert entry is not None and entry["project_id"] == project


# --- a1: the project CRUD endpoints + assignment over HTTP --------------------
def test_project_endpoints(
    client: TestClient, make_initiative: Callable[[], str], track_projects: list[str]
):
    r = client.post("/projects", json={"name": "API Project", "intent": "via http"})
    assert r.status_code == 201, r.text
    proj = r.json()
    track_projects.append(proj["id"])
    assert proj["id"] == "api-project"  # BD-11: ID is the full name slug
    assert proj["intent"] == "via http"

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
    assert all("state" in i and "title" in i for i in d["initiatives"])  # nav fields
    assert d["open_decisions"] >= 1  # the escalation is counted project-wide

    assert client.get("/projects/ghost/dashboard").status_code == 404


# --- 0011 a8: the dashboard carries per-initiative attention indicators --------
def test_project_dashboard_attention_counts(
    client: TestClient, make_initiative: Callable[[], str], track_projects: list[str]
):
    proj = client.post("/projects", json={"name": "Attn Project", "intent": "x"}).json()
    track_projects.append(proj["id"])
    iid = make_initiative()
    client.post(f"/initiatives/{iid}/project", json={"project_id": proj["id"]})

    # set one proposed constraint + one acceptance criterion in a single PUT
    r = client.put(
        f"/specs/{iid}",
        json={
            "initiative_id": iid, "title": "T", "version": 0,
            "constraints": [{"text": "c", "provenance": "ai_proposed", "status": "proposed"}],
            "acceptance": [{"text": "ac", "provenance": "human", "status": "confirmed",
                            "verify": {"kind": "behavior", "detail": "check it"}}],
        },
    )
    assert r.status_code == 200, r.text
    crit_id = r.json()["acceptance"][0]["id"]

    # one open decision (awaiting a verdict)
    _store_run(lambda s: s.raise_decision(Decision(question="q?", options=["a", "b"]), iid))

    # submit evidence for the criterion (awaiting the human's verdict)
    _store_run(
        lambda s: s.submit_evidence(iid, [{"criterion_id": crit_id, "evidence": "done"}])
    )

    d = client.get(f"/projects/{proj['id']}/dashboard").json()
    a = d["attention"][iid]
    assert a["proposed_items"] == 1
    assert a["open_decisions"] == 1
    assert a["criteria_to_verify"] == 1




# --- BD-11: archive and unarchive a project -----------------------------------
def test_archive_unarchive_project(client: TestClient, track_projects: list[str]):
    proj = client.post("/projects", json={"name": "Archivable", "intent": "x"}).json()
    pid = proj["id"]
    track_projects.append(pid)

    assert not proj["archived"]

    # archive it — returns the project with archived=True
    r = client.post(f"/projects/{pid}/archive")
    assert r.status_code == 200, r.text
    assert r.json()["archived"] is True

    # idempotent — archiving again is a no-op
    r2 = client.post(f"/projects/{pid}/archive")
    assert r2.status_code == 200 and r2.json()["archived"] is True

    # still accessible at its canonical URL
    got = client.get(f"/projects/{pid}")
    assert got.status_code == 200 and got.json()["archived"] is True

    # appears in the project list with archived=True
    projects = client.get("/projects").json()
    match = next((p for p in projects if p["id"] == pid), None)
    assert match is not None and match["archived"] is True

    # unarchive — restores active state, no data loss
    r3 = client.post(f"/projects/{pid}/unarchive")
    assert r3.status_code == 200 and r3.json()["archived"] is False

    # 404 for an unknown project
    assert client.post("/projects/ghost/archive").status_code == 404
    assert client.post("/projects/ghost/unarchive").status_code == 404
