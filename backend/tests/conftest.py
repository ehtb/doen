"""Test fixtures.

These are integration tests: they need the docker-compose Postgres + Redis up.
The TestClient context manager runs the app lifespan, so it connects for real.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import DATABASE_URL
from app.main import app
from app.migrate import run_migrations

_TEST_PROJECT_IDS = (
    "test-suite",
    "launch-hosted-tier",
    "same-project",
    "group-a",
    "group-b",
    "api-project",
    "orphan-test",
)


def _run(coro: Awaitable) -> object:
    return asyncio.run(coro)


async def _exec(sql: str, *args: object) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    async def go() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            # Clean up stale test projects left by previous runs whose teardown failed.
            await conn.execute(
                "DELETE FROM initiatives WHERE project_id = ANY($1::text[])",
                list(_TEST_PROJECT_IDS),
            )
            await conn.execute(
                "DELETE FROM projects WHERE id = ANY($1::text[])",
                list(_TEST_PROJECT_IDS),
            )
            await run_migrations(conn)
        finally:
            await conn.close()

    _run(go())


# session-scoped so the MCP StreamableHTTPSessionManager runs only once per test session
@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def project(client: TestClient) -> str:
    """A project created once per test session; the default owner for make_initiative."""
    r = client.post("/projects", json={"name": "Test Suite", "intent": "automated test project"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]  # "test-suite"
    yield pid

    async def drop() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            await conn.execute("DELETE FROM initiatives WHERE project_id = $1", pid)
            await conn.execute("DELETE FROM projects WHERE id = $1", pid)
        finally:
            await conn.close()

    _run(drop())


@pytest.fixture
def make_initiative(client: TestClient, project: str) -> Callable[[], str]:
    """Create initiatives via the API and drop them on teardown. Each gets a unique title
    so the derived slug never collides across tests. Defaults to the session test project."""
    created: list[str] = []

    def make(title: str | None = None, project_id: str | None = None) -> str:
        r = client.post(
            "/initiatives",
            json={"title": title or f"Test {uuid4().hex[:8]}", "project_id": project_id or project},
        )
        assert r.status_code == 201, r.text
        iid = r.json()["id"]
        created.append(iid)
        return iid

    yield make
    _run(_drop(created))


async def _drop(ids: list[str]) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        for iid in ids:
            await conn.execute("DELETE FROM initiatives WHERE id = $1", iid)
    finally:
        await conn.close()
