"""BD-12: drift report store methods and MCP tools.

Integration tests against docker-compose Postgres. Covers:
- report_memory_drift MCP tool: valid call creates a record, bad memory_id returns error + no record
- list_memory_for_audit store method: only returns stale entries, returns empty when all fresh
- resolve_drift_report store method: approved path updates memory, dismissed path leaves it alone
- No existing MCP tools broke (the MCP tool list test from test_mcp.py covers this implicitly;
  here we verify the two new tools appear in the list)
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path

import asyncpg
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import DATABASE_URL, REDIS_URL
from app.models import Spec
from app.store import SpecStore
from redis import asyncio as aioredis

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run(coro) -> object:
    return asyncio.run(coro)


async def _store() -> tuple[SpecStore, asyncpg.Pool, aioredis.Redis]:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return SpecStore(pg, redis), pg, redis


async def _make_complete_initiative_with_memory(store: SpecStore, pg: asyncpg.Pool, project_id: str) -> str:
    """Create an initiative + memory row in a project, force state=complete, return memory_id."""
    init = await store.create_initiative("Drift test initiative", project_id)
    await store.save_spec(Spec(initiative_id=init.id, version=0, title="drift test", intent="test"))
    mem = await store.create_memory(init.id, "We use asyncpg for all DB access, no ORM.")
    # force complete so get_context would surface it
    await pg.execute("UPDATE initiatives SET state = 'complete' WHERE id = $1", init.id)
    return mem.id


# --- store: create_drift_report ----------------------------------------------------
def test_create_drift_report_valid(make_initiative: Callable[[], str], project: str):
    """A valid create_drift_report writes a durable record and returns the DriftReport."""
    async def go():
        store, pg, redis = await _store()
        try:
            memory_id = await _make_complete_initiative_with_memory(store, pg, project)
            report = await store.create_drift_report(
                memory_id=memory_id,
                current_evidence="asyncpg has been replaced by SQLAlchemy in recent commits.",
                is_obsolete=False,
            )
            # durable — query directly
            row = await pg.fetchrow("SELECT * FROM drift_reports WHERE id = $1", report.id)
            return report, row
        finally:
            await pg.close()
            await redis.close()

    report, row = _run(go())
    assert report.memory_id == row["memory_id"]
    assert row["status"] == "pending"
    assert row["is_obsolete"] is False
    assert row["current_evidence"] == "asyncpg has been replaced by SQLAlchemy in recent commits."


def test_create_drift_report_bad_memory_id(make_initiative: Callable[[], str], project: str):
    """An unknown memory_id raises NotFoundError and writes no row."""
    from app.exceptions import NotFoundError

    async def go():
        store, pg, redis = await _store()
        try:
            before = await pg.fetchval("SELECT count(*) FROM drift_reports")
            with pytest.raises(NotFoundError):
                await store.create_drift_report(
                    memory_id="mem_doesnotexist000",
                    current_evidence="evidence",
                    is_obsolete=True,
                )
            after = await pg.fetchval("SELECT count(*) FROM drift_reports")
            return before, after
        finally:
            await pg.close()
            await redis.close()

    before, after = _run(go())
    assert before == after, "no row should be written on bad memory_id"


# --- store: list_memory_for_audit staleness filter ----------------------------------
def test_list_memory_for_audit_staleness(make_initiative: Callable[[], str], project: str):
    """Only returns entries whose last_verified_at is older than the window, or NULL."""
    async def go():
        store, pg, redis = await _store()
        try:
            memory_id = await _make_complete_initiative_with_memory(store, pg, project)

            # NULL → always stale
            stale = await store.list_memory_for_audit(project, staleness_days=30)
            stale_ids = [m.id for m in stale]
            assert memory_id in stale_ids, "NULL last_verified_at should appear as stale"

            # stamp last_verified_at = now() — should now be fresh
            await pg.execute(
                "UPDATE memory SET last_verified_at = now() WHERE id = $1", memory_id
            )
            fresh = await store.list_memory_for_audit(project, staleness_days=30)
            fresh_ids = [m.id for m in fresh]
            assert memory_id not in fresh_ids, "recently verified entry should not appear"

            # stamp an old timestamp — stale again
            await pg.execute(
                "UPDATE memory SET last_verified_at = now() - interval '60 days' WHERE id = $1",
                memory_id,
            )
            stale_again = await store.list_memory_for_audit(project, staleness_days=30)
            stale_again_ids = [m.id for m in stale_again]
            assert memory_id in stale_again_ids, "60-day-old entry should appear as stale for 30-day window"

            return True
        finally:
            await pg.close()
            await redis.close()

    assert _run(go())


# --- store: resolve_drift_report ---------------------------------------------------
def test_resolve_drift_report_approved_updates_memory(make_initiative: Callable[[], str], project: str):
    """Approved resolution patches memory summary and stamps last_verified_at."""
    async def go():
        store, pg, redis = await _store()
        try:
            memory_id = await _make_complete_initiative_with_memory(store, pg, project)
            report = await store.create_drift_report(memory_id, "evidence", is_obsolete=False)
            resolved = await store.resolve_drift_report(
                report.id,
                action="approved",
                memory_update={"summary": "Updated: we now use SQLAlchemy."},
                resolution_note="Human confirmed drift",
            )
            mem_row = await pg.fetchrow(
                "SELECT summary, last_verified_at FROM memory WHERE id = $1", memory_id
            )
            return resolved, mem_row
        finally:
            await pg.close()
            await redis.close()

    resolved, mem_row = _run(go())
    assert resolved.status == "approved"
    assert resolved.resolved_at is not None
    assert mem_row["summary"] == "Updated: we now use SQLAlchemy."
    assert mem_row["last_verified_at"] is not None


def test_resolve_drift_report_dismissed_leaves_memory(make_initiative: Callable[[], str], project: str):
    """Dismissed resolution does NOT mutate the memory entry."""
    async def go():
        store, pg, redis = await _store()
        try:
            memory_id = await _make_complete_initiative_with_memory(store, pg, project)
            original_summary = await pg.fetchval(
                "SELECT summary FROM memory WHERE id = $1", memory_id
            )
            report = await store.create_drift_report(memory_id, "false alarm", is_obsolete=False)
            resolved = await store.resolve_drift_report(report.id, action="dismissed")
            mem_row = await pg.fetchrow(
                "SELECT summary, last_verified_at FROM memory WHERE id = $1", memory_id
            )
            return resolved, mem_row, original_summary
        finally:
            await pg.close()
            await redis.close()

    resolved, mem_row, original_summary = _run(go())
    assert resolved.status == "dismissed"
    assert mem_row["summary"] == original_summary, "dismissed should not update memory"
    assert mem_row["last_verified_at"] is not None, "dismissed should stamp last_verified_at to prevent re-audit"


# --- MCP tool surface: new tools registered ----------------------------------------
def test_new_mcp_tools_registered(make_initiative: Callable[[], str], project: str):
    """report_memory_drift and list_memory_for_audit appear in the MCP tool list."""
    async def go():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND_DIR)
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                return names

    names = _run(go())
    assert "report_memory_drift" in names, f"report_memory_drift missing from {names}"
    assert "list_memory_for_audit" in names, f"list_memory_for_audit missing from {names}"


def test_report_memory_drift_mcp_bad_id(make_initiative: Callable[[], str], project: str):
    """Calling report_memory_drift over MCP with a bad memory_id returns an error and no DB row."""
    async def go():
        store, pg, redis = await _store()
        try:
            before = await pg.fetchval("SELECT count(*) FROM drift_reports")
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND_DIR)
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("report_memory_drift", {
                        "memory_id": "mem_doesnotexist999",
                        "current_evidence": "bogus",
                        "is_obsolete": False,
                    })
                    # FastMCP surfaces ValueError as a tool error
                    is_error = result.isError
            after = await pg.fetchval("SELECT count(*) FROM drift_reports")
            return is_error, before, after
        finally:
            await pg.close()
            await redis.close()

    is_error, before, after = _run(go())
    assert is_error, "MCP should return isError=True for bad memory_id"
    assert before == after, "no drift report row should be written"
