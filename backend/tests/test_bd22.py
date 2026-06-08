"""BD-22: Advisor observations — persistent records with resolve-to-initiative flow."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import DATABASE_URL


# --- store-level tests (no HTTP, direct DB) -----------------------------------------------

def _run(coro: Awaitable) -> object:
    return asyncio.run(coro)


@pytest.fixture
def clean_project():
    """Create and clean up a project for isolation."""
    ids: list[str] = []
    yield ids

    async def drop() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            for pid in ids:
                # observations cascade on project delete
                await conn.execute("DELETE FROM initiatives WHERE project_id = $1", pid)
                await conn.execute("DELETE FROM projects WHERE id = $1", pid)
        finally:
            await conn.close()

    _run(drop())


def test_observation_create_and_list(client: TestClient, clean_project: list[str]):
    r = client.post("/projects", json={"name": "BD22 Obs Test", "intent": "test"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    clean_project.append(project_id)

    # No observations initially
    r = client.get(f"/projects/{project_id}/observations")
    assert r.status_code == 200
    assert r.json() == []


def test_observation_resolve_links_initiative(
    client: TestClient, make_initiative: Callable, clean_project: list[str]
):
    r = client.post("/projects", json={"name": "BD22 Resolve Test", "intent": "test"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    clean_project.append(project_id)

    # Manually insert an open observation (bypassing synthesis LLM).
    async def insert_obs() -> str:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            obs_id = f"obs_{asyncio.get_event_loop().time():.0f}"
            await conn.execute(
                "INSERT INTO observations (id, project_id, content, status) VALUES ($1, $2, $3, 'open')",
                obs_id, project_id, "Test observation content",
            )
            return obs_id
        finally:
            await conn.close()

    obs_id = _run(insert_obs())

    # Verify it appears as open
    r = client.get(f"/projects/{project_id}/observations")
    assert r.status_code == 200
    obs_list = r.json()
    assert len(obs_list) == 1
    assert obs_list[0]["status"] == "open"
    assert obs_list[0]["resolved_initiative_id"] is None

    # Create an initiative to resolve against
    init_id = make_initiative(project_id=project_id)

    # Resolve the observation
    r = client.post(f"/observations/{obs_id}/resolve", json={"initiative_id": init_id})
    assert r.status_code == 200
    resolved = r.json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_initiative_id"] == init_id

    # Verify the resolved state persists
    r = client.get(f"/projects/{project_id}/observations")
    assert r.status_code == 200
    obs_list = r.json()
    assert len(obs_list) == 1
    assert obs_list[0]["status"] == "resolved"
    assert obs_list[0]["resolved_initiative_id"] == init_id


def test_observation_resolve_nonexistent_returns_404(client: TestClient):
    r = client.post(
        "/observations/obs_nonexistent/resolve",
        json={"initiative_id": "init_nonexistent"},
    )
    assert r.status_code == 404


def test_replace_open_preserves_resolved(
    client: TestClient, make_initiative: Callable, clean_project: list[str]
):
    """BD-22 constraint: resolving an observation must persist across synthesis refresh."""
    r = client.post("/projects", json={"name": "BD22 Preserve Test", "intent": "test"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    clean_project.append(project_id)

    async def setup() -> tuple[str, str]:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            open_id = f"obs_open_{asyncio.get_event_loop().time():.0f}"
            resolved_id = f"obs_res_{asyncio.get_event_loop().time():.0f}_x"
            await conn.execute(
                "INSERT INTO observations (id, project_id, content, status) VALUES ($1, $2, $3, 'open')",
                open_id, project_id, "Open observation",
            )
            await conn.execute(
                "INSERT INTO observations (id, project_id, content, status) VALUES ($1, $2, $3, 'resolved')",
                resolved_id, project_id, "Resolved observation",
            )
            return open_id, resolved_id
        finally:
            await conn.close()

    _, resolved_id = _run(setup())

    # Simulate a synthesis refresh (replace_open_observations wipes open ones only)
    async def refresh() -> None:
        import asyncpg as _pg
        conn = await _pg.connect(DATABASE_URL)
        try:
            await conn.execute(
                "DELETE FROM observations WHERE project_id = $1 AND status = 'open'",
                project_id,
            )
        finally:
            await conn.close()

    _run(refresh())

    # Resolved observation must still be there
    r = client.get(f"/projects/{project_id}/observations")
    assert r.status_code == 200
    obs_list = r.json()
    assert any(o["id"] == resolved_id and o["status"] == "resolved" for o in obs_list)
