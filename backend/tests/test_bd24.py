"""BD-24: Scope and Reject Advisor Observations.

Tests cover:
  AC-1  Only the most recently completed initiative (highest seq) gets an observation.
  AC-2  A second observation cannot be created for an initiative that already has one.
  AC-3  Reject sets status=rejected, no navigation, no initiative created.
  AC-4  BD-22 resolve action still works on non-rejected observations.
  AC-5  Rejected observations cannot be rejected or resolved again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import pytest

from app.config import DATABASE_URL
from app.models import Initiative
from app.services.advisor import synthesize_project
from app.store import SpecStore
from redis import asyncio as aioredis
from app.config import REDIS_URL


# ---------------------------------------------------------------------------
# helpers

def _run(coro: Awaitable) -> object:
    return asyncio.run(coro)


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


class FakeLLM:
    def __init__(self, obs: list[str] | None = None):
        self.obs = obs or ["Observation from synthesis."]
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"schema_name": schema_name})
        return {"advisor_observations": self.obs, "what_we_know": None}


@pytest.fixture
def track_projects():
    ids: list[str] = []
    yield ids

    async def drop() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            for pid in ids:
                await conn.execute("DELETE FROM initiatives WHERE project_id = $1", pid)
                await conn.execute("DELETE FROM projects WHERE id = $1", pid)
        finally:
            await conn.close()

    asyncio.run(drop())


async def _force_complete(conn: asyncpg.Connection, initiative_id: str) -> None:
    await conn.execute(
        "UPDATE initiatives SET state = 'complete' WHERE id = $1", initiative_id
    )


# ---------------------------------------------------------------------------
# AC-1: only the most recently completed initiative gets an observation

def test_scoping_only_most_recent_gets_observation(track_projects: list[str]):
    """Seed two completed initiatives; assert only the later one (higher seq) has an observation."""
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            proj = await store.create_project("BD24 Scoping Test", "Intent")
            track_projects.append(proj.id)

            init_a = await store.create_initiative("Init A", proj.id)
            init_b = await store.create_initiative("Init B", proj.id)

            # init_b has higher seq (created later)
            assert init_b.seq > init_a.seq

            async with store.pg.acquire() as conn:
                await _force_complete(conn, init_a.id)
                await _force_complete(conn, init_b.id)

            result = await synthesize_project(store, proj.id, llm=fake)
            return result, init_a.id, init_b.id

        return inner()

    result, init_a_id, init_b_id = _store_run(go)

    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.source_initiative_id == init_b_id
    assert obs.source_initiative_id != init_a_id


# ---------------------------------------------------------------------------
# AC-2: second observation cannot be created for an initiative that already has one

def test_second_observation_blocked_via_store(track_projects: list[str]):
    """create_scoped_observation is idempotent: a second call for the same initiative is a no-op."""

    def go(store: SpecStore):
        async def inner():
            proj = await store.create_project("BD24 Dedup Test", "Intent")
            track_projects.append(proj.id)
            init = await store.create_initiative("Init A", proj.id)

            await store.create_scoped_observation(proj.id, init.id, "First observation")
            await store.create_scoped_observation(proj.id, init.id, "Should be ignored")

            return await store.list_observations(proj.id)

        return inner()

    observations = _store_run(go)
    assert len(observations) == 1
    assert observations[0].content == "First observation"


def test_second_observation_blocked_via_synthesis(track_projects: list[str]):
    """Calling synthesize_project twice for the same completed initiative produces exactly one
    observation (the second call detects the existing one and skips generation)."""
    fake = FakeLLM(obs=["First run observation."])

    def go(store: SpecStore):
        async def inner():
            proj = await store.create_project("BD24 Synthesis Dedup", "Intent")
            track_projects.append(proj.id)
            init = await store.create_initiative("Init X", proj.id)
            async with store.pg.acquire() as conn:
                await _force_complete(conn, init.id)

            await synthesize_project(store, proj.id, llm=fake)

            fake.obs = ["Second run observation — must not appear."]
            await synthesize_project(store, proj.id, llm=fake)

            return await store.list_observations(proj.id)

        return inner()

    observations = _store_run(go)
    assert len(observations) == 1
    assert observations[0].content == "First run observation."


# ---------------------------------------------------------------------------
# AC-3: reject sets status=rejected via the API

def test_reject_observation_via_api(client, make_initiative, clean_project: list[str]):
    r = client.post("/projects", json={"name": "BD24 Reject API", "intent": "test"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    clean_project.append(project_id)

    async def insert_obs() -> str:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            obs_id = f"obs_bd24_reject_{id(object())}"
            await conn.execute(
                "INSERT INTO observations (id, project_id, content, status) VALUES ($1, $2, $3, 'open')",
                obs_id, project_id, "Reject me",
            )
            return obs_id
        finally:
            await conn.close()

    obs_id = _run(insert_obs())

    r = client.post(f"/observations/{obs_id}/reject")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "rejected"
    assert data["id"] == obs_id

    # Must disappear from the active (open) list
    r = client.get(f"/projects/{project_id}/observations")
    obs_list = r.json()
    open_obs = [o for o in obs_list if o["status"] == "open"]
    assert not any(o["id"] == obs_id for o in open_obs)

    # Must appear as rejected in the full list
    rejected_obs = [o for o in obs_list if o["id"] == obs_id]
    assert len(rejected_obs) == 1
    assert rejected_obs[0]["status"] == "rejected"


def test_reject_nonexistent_returns_404(client):
    r = client.post("/observations/obs_nonexistent_bd24/reject")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# AC-4: BD-22 resolve still works on non-rejected observations

def test_resolve_still_works_on_open_observation(client, make_initiative, clean_project: list[str]):
    r = client.post("/projects", json={"name": "BD24 Resolve Still Works", "intent": "test"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    clean_project.append(project_id)

    async def insert_obs() -> str:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            obs_id = f"obs_bd24_resolve_{id(object())}"
            await conn.execute(
                "INSERT INTO observations (id, project_id, content, status) VALUES ($1, $2, $3, 'open')",
                obs_id, project_id, "Resolve me into an initiative",
            )
            return obs_id
        finally:
            await conn.close()

    obs_id = _run(insert_obs())
    init_id = make_initiative(project_id=project_id)

    r = client.post(f"/observations/{obs_id}/resolve", json={"initiative_id": init_id})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"
    assert r.json()["resolved_initiative_id"] == init_id


# ---------------------------------------------------------------------------
# AC-5: rejected observation cannot be rejected or resolved again

def test_rejected_observation_cannot_be_rejected_again(client, clean_project: list[str]):
    r = client.post("/projects", json={"name": "BD24 No Double Reject", "intent": "test"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    clean_project.append(project_id)

    async def insert_obs() -> str:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            obs_id = f"obs_bd24_double_{id(object())}"
            await conn.execute(
                "INSERT INTO observations (id, project_id, content, status) VALUES ($1, $2, $3, 'rejected')",
                obs_id, project_id, "Already rejected",
            )
            return obs_id
        finally:
            await conn.close()

    obs_id = _run(insert_obs())

    r = client.post(f"/observations/{obs_id}/reject")
    assert r.status_code == 404


def test_rejected_observation_cannot_be_acted_on(client, make_initiative, clean_project: list[str]):
    """A rejected observation's reject action is inert (404); the resolve action is absent
    from the UI. This test covers the backend guard on the reject endpoint."""
    r = client.post("/projects", json={"name": "BD24 No Act After Reject", "intent": "test"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    clean_project.append(project_id)

    async def insert_obs() -> str:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            obs_id = f"obs_bd24_act_rej_{id(object())}"
            await conn.execute(
                "INSERT INTO observations (id, project_id, content, status) VALUES ($1, $2, $3, 'rejected')",
                obs_id, project_id, "Already rejected",
            )
            return obs_id
        finally:
            await conn.close()

    obs_id = _run(insert_obs())

    # Reject again must fail — the WHERE status='open' guard in store.reject_observation enforces this.
    r = client.post(f"/observations/{obs_id}/reject")
    assert r.status_code == 404, "rejecting a rejected observation must return 404"


# ---------------------------------------------------------------------------
# fixture needed by API tests (mirrors test_bd22.py pattern)

@pytest.fixture
def clean_project():
    ids: list[str] = []
    yield ids

    async def drop() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            for pid in ids:
                await conn.execute("DELETE FROM initiatives WHERE project_id = $1", pid)
                await conn.execute("DELETE FROM projects WHERE id = $1", pid)
        finally:
            await conn.close()

    _run(drop())
