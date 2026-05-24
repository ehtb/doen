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
from app.store import Spec, SpecStore

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _data(result) -> dict:
    assert not result.isError, getattr(result.content[0], "text", result)
    return json.loads(result.content[0].text)


async def _flow() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pool, redis)
    iid = f"init_{uuid4().hex[:12]}"

    # Seed an initiative + spec for get_spec to find.
    await pool.execute(
        "INSERT INTO initiatives (id, org_id, owner_id, stage) VALUES ($1,$2,$3,'shape')",
        iid, DEV_ORG_ID, DEV_USER_ID,
    )
    await store.save_spec(Spec(initiative_id=iid, title="MCP demo", intent="prove a4"))

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND_DIR)
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # all four tools are exposed
                names = {t.name for t in (await session.list_tools()).tools}
                assert {"get_spec", "raise_decision", "resolve_decision",
                        "wait_for_decision"} <= names, names

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
        await pool.close()
        await redis.aclose()


def test_mcp_tools_over_stdio():
    asyncio.run(_flow())
