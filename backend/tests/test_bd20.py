"""BD-20: Guided discovery and project synthesis tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.models import Message, Project
from app.services.advisor import advise_project_discovery, synthesize_project
from app.store import SpecStore


class FakeLLM:
    def __init__(self, discovery_payload=None, synthesis_payload=None):
        self.discovery_payload = discovery_payload or {
            "reply": "Discovery question?",
            "proposed_initiative": None,
            "proposed_initiative_type": None
        }
        self.synthesis_payload = synthesis_payload or {
            "advisor_observations": "Looks good.",
            "what_we_know": {
                "patterns": "p",
                "assumptions": "a",
                "intent_alignment": "i"
            }
        }
        self.calls = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if schema_name == "discovery_reply":
            return self.discovery_payload
        if schema_name == "project_synthesis":
            return self.synthesis_payload
        return {}


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


def test_advise_project_discovery_returns_reply(track_projects: list[str]):
    fake = FakeLLM(discovery_payload={
        "reply": "What is the problem?",
        "proposed_initiative": "Test initiative",
        "proposed_initiative_type": "engineering"
    })
    
    def go(store: SpecStore):
        async def inner():
            proj = await store.create_project("Discovery Test", "Intent")
            track_projects.append(proj.id)
            reply, proposed, p_type = await advise_project_discovery(
                store, proj.id, "I have an idea", [], llm=fake
            )
            return reply, proposed, p_type
        return inner()

    reply, proposed, p_type = _store_run(go)
    assert reply.content == "What is the problem?"
    assert proposed == "Test initiative"
    assert p_type == "engineering"
    assert "GUIDED DISCOVERY MODE" in fake.calls[0]["system"]


def test_synthesize_project_no_completed_initiatives(track_projects: list[str]):
    def go(store: SpecStore):
        async def inner():
            proj = await store.create_project("Synthesis Test 0", "Intent")
            track_projects.append(proj.id)
            return await synthesize_project(store, proj.id)
        return inner()

    res = _store_run(go)
    assert res.advisor_observations is None
    assert res.what_we_know is None
    assert res.completed_count == 0


def test_synthesize_project_with_completed_initiatives(track_projects: list[str]):
    fake = FakeLLM(synthesis_payload={
        "advisor_observations": "Found some patterns.",
        "what_we_know": {
            "patterns": "Pattern A",
            "assumptions": "Assumption B",
            "intent_alignment": "Aligned"
        }
    })

    def go(store: SpecStore):
        async def inner():
            proj = await store.create_project("Synthesis Test 5", "Intent")
            track_projects.append(proj.id)
            
            # Create 5 completed initiatives
            for i in range(5):
                init = await store.create_initiative(f"Init {i}", proj.id)
                await store.pg.execute(
                    "UPDATE initiatives SET state = 'complete' WHERE id = $1", init.id
                )
            
            return await synthesize_project(store, proj.id, llm=fake)
        return inner()

    res = _store_run(go)
    assert res.advisor_observations == "Found some patterns."
    assert res.what_we_know.patterns == "Pattern A"
    assert res.completed_count == 5
    assert "Generate advisor_observations" in fake.calls[0]["user"]
    assert "include — ≥5 completed" in fake.calls[0]["user"]
