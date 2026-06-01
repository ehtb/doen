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
            await run_migrations(conn)
        finally:
            await conn.close()

    _run(go())


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_initiative(client: TestClient) -> Callable[[], str]:
    """Create dev initiatives via the API and drop them (cascade) on teardown. Each gets a
    unique title so the derived slug never collides across tests; the slug is the id. Every
    initiative belongs to a project (no orphan specs) — the always-present 'build-doen' project
    (created by migration 0006) is the default owner."""
    created: list[str] = []

    def make(title: str | None = None, project_id: str = "build-doen") -> str:
        r = client.post(
            "/initiatives",
            json={"title": title or f"Test {uuid4().hex[:8]}", "project_id": project_id},
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


@pytest.fixture
def delete_spec_row() -> Callable[[str], None]:
    """Delete the source-of-truth row directly, leaving the Redis cache intact."""

    def _del(initiative_id: str) -> None:
        _run(_exec("DELETE FROM specs WHERE initiative_id = $1", initiative_id))

    return _del
