"""a4 — drive the MCP server for real over stdio: spawn it as a subprocess, speak
the protocol, and exercise every tool. Needs the docker-compose Postgres + Redis up.

The await path mirrors production: the executor blocks on wait_for_decision while a
*different* client (here, the test acting as the human, via its own store) resolves
it — the wake crosses connections through Redis pub/sub.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from redis import asyncio as aioredis

from app.config import DATABASE_URL, DEV_ORG_ID, DEV_USER_ID, REDIS_URL
from app.models import Spec
from app.providers.llm import LLMError
from app.services.shaping import create_from_description, infer_initiative_type
from app.store import SpecStore

SHAPING_PAYLOAD = {
    "title": "Passwordless sign-in",
    "intent": "Let users sign in without a password.",
    "constraints": ["Links expire in 15 minutes.", "No password stored."],
    "discretion": ["Email template copy."],
    "acceptance": [
        {
            "text": "A used link is rejected. [HEADLINE]",
            "verify": {"kind": "test", "detail": "Replay a consumed link; assert 4xx."},
        }
    ],
    "units": [],
}


class _FakeLLM:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        if self.error:
            raise self.error
        return self.payload

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _data(result) -> dict:
    assert not result.isError, getattr(result.content[0], "text", result)
    return json.loads(result.content[0].text)


async def _flow() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pool, redis)

    proj = await store.create_project(f"MCP Test {uuid4().hex[:6]}", "drive MCP tools in test")
    init = await store.create_initiative("MCP demo", proj.id)
    iid = init.id
    await store.save_spec(Spec(initiative_id=iid, version=0, title="MCP demo", intent="prove a4"))

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND_DIR)
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # all original tools plus create_spec are exposed
                names = {t.name for t in (await session.list_tools()).tools}
                assert {"get_spec", "raise_decision", "resolve_decision",
                        "wait_for_decision", "create_spec"} <= names, names

                # get_spec returns the whole spec
                spec = _data(await session.call_tool("get_spec", {"initiative_id": iid}))
                assert spec["title"] == "MCP demo"
                assert spec["version"] == 1

                # raise + resolve roundtrip, both through MCP
                raised = _data(await session.call_tool("raise_decision", {
                    "initiative_id": iid,
                    "question": "stdio or http?",
                    "options": ["stdio", "http"],
                    "recommendation": "stdio",
                }))
                assert raised["status"] == "open"
                resolved = _data(await session.call_tool("resolve_decision", {
                    "decision_id": raised["id"],
                    "chosen": "stdio",
                    "rationale": "local dogfooding, zero auth friction",
                    "decided_by": "edo",
                }))
                assert resolved["status"] == "resolved"
                assert resolved["chosen"] == "stdio"

                # create_spec: empty prompt -> error, no write
                r_empty = await session.call_tool(
                    "create_spec", {"project_id": proj.id, "prompt": "   "}
                )
                assert r_empty.isError, "expected error for empty prompt"

                # create_spec: non-existent project -> error, no write
                r_ghost = await session.call_tool(
                    "create_spec", {"project_id": "ghost-000", "prompt": "build login page"}
                )
                assert r_ghost.isError, "expected error for unknown project"

                # await path: block on wait_for_decision; resolve out-of-band (the human)
                d2 = _data(await session.call_tool("raise_decision", {
                    "initiative_id": iid,
                    "question": "ship it?",
                    "options": ["yes", "no"],
                }))
                wait_task = asyncio.create_task(
                    session.call_tool("wait_for_decision",
                                      {"decision_id": d2["id"], "timeout": 15})
                )
                await asyncio.sleep(0.5)  # let the server subscribe before we publish
                await store.resolve_decision(d2["id"], "yes", "looks good", "edo")
                woken = _data(await wait_task)
                assert woken["status"] == "resolved"
                assert woken["chosen"] == "yes"
    finally:
        await pool.execute("DELETE FROM initiatives WHERE id = $1", iid)
        await pool.execute("DELETE FROM projects WHERE id = $1", proj.id)
        await pool.close()
        await redis.close()


def test_mcp_tools_over_stdio():
    asyncio.run(_flow())


# --- BD-28: create_spec service-level and type inference tests (FakeLLM + real DB) ---

async def _create_spec_service_flow() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pool, redis)

    proj = await store.create_project(f"cs-test-{uuid4().hex[:6]}", "create_spec test")
    created_ids: list[str] = []
    try:
        # happy path: returns initiative_id, initiative_type, and all four spec sections
        init = await create_from_description(
            store, proj.id, "add passwordless sign-in via email magic links",
            initiative_type="engineering", llm=_FakeLLM(SHAPING_PAYLOAD),
        )
        created_ids.append(init.id)
        spec = await store.get_spec(init.id)
        assert spec is not None, "spec not retrievable after creation"
        assert spec.intent, "intent missing"
        assert spec.constraints, "constraints missing"
        assert spec.acceptance, "acceptance missing"
        assert init.initiative_type == "engineering"
        assert "-" in init.id and init.id.split("-")[-1].isdigit(), f"unexpected id shape: {init.id}"

        # infer_initiative_type: engineering prompts
        engineering_prompts = [
            "build a login page",
            "add dark mode support to the web app",
        ]
        for p in engineering_prompts:
            t = await infer_initiative_type(p, llm=_FakeLLM({"initiative_type": "engineering"}))
            assert t == "engineering", f"expected engineering for {p!r}"

        # infer_initiative_type: research prompts
        research_prompts = [
            "research competing approaches to distributed caching",
            "evaluate three LLM providers for cost and quality",
        ]
        for p in research_prompts:
            t = await infer_initiative_type(p, llm=_FakeLLM({"initiative_type": "research"}))
            assert t == "research", f"expected research for {p!r}"

        # infer_initiative_type: falls back to engineering on LLMError
        t = await infer_initiative_type("x", llm=_FakeLLM(error=LLMError("boom")))
        assert t == "engineering", "expected engineering fallback on LLMError"

    finally:
        for iid in created_ids:
            await pool.execute("DELETE FROM initiatives WHERE id = $1", iid)
        await pool.execute("DELETE FROM projects WHERE id = $1", proj.id)
        await pool.close()
        await redis.close()


def test_create_spec_service_and_type_inference():
    asyncio.run(_create_spec_service_flow())
