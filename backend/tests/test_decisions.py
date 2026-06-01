"""Steering rail backend — the human half of the escalation loop.

Acceptance coverage for the decision endpoints:
  a1 — GET /initiatives/{id}/decisions returns the durable open set from Postgres.
  a2 — POST /decisions/{id}/resolve records chosen/rationale/decided_by, status=resolved.
  a5 — decisions survive a Redis FLUSHALL (the cache is derived; PG is truth).

Plus the boundary guards on resolve (404 / 409 / 422). The MCP-wake criterion (a3)
and the inline-resolve UI (a4) are behaviour/judgment — verified end-to-end with the
web rail, not here.

Needs the docker-compose Postgres + Redis up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import asyncpg
from fastapi.testclient import TestClient
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.store import Decision, SpecStore


def _run(coro) -> object:
    return asyncio.run(coro)


async def _raise(iid: str, question: str, options: list[str], rec: str | None = None) -> str:
    """Raise a decision the way an executor would (SpecStore.raise_decision)."""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        d = await SpecStore(pool, redis).raise_decision(
            Decision(question=question, options=options, recommendation=rec), iid
        )
        return d.id
    finally:
        await pool.close()
        await redis.aclose()


async def _read_row(decision_id: str) -> dict:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            "SELECT payload, status FROM decisions WHERE id = $1", decision_id
        )
        return {"status": row["status"], "payload": Decision.model_validate_json(row["payload"])}
    finally:
        await conn.close()


async def _flushall() -> None:
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis.flushall()
    finally:
        await redis.aclose()


def test_list_open_decisions(client: TestClient, make_initiative: Callable[[], str]):
    # a1 — the rail's feed is the durable open set, oldest first.
    iid = make_initiative()
    first = _run(_raise(iid, "stdio or http?", ["stdio", "http"], rec="stdio"))
    second = _run(_raise(iid, "ship it?", ["yes", "no"]))

    r = client.get(f"/initiatives/{iid}/decisions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["id"] for d in body] == [first, second]  # FIFO
    assert body[0]["question"] == "stdio or http?"
    assert body[0]["options"] == ["stdio", "http"]
    assert body[0]["recommendation"] == "stdio"
    assert all(d["status"] == "open" for d in body)


def test_resolve_records_verdict(client: TestClient, make_initiative: Callable[[], str]):
    # a2 — resolving writes the verdict to the durable row and flips status.
    iid = make_initiative()
    did = _run(_raise(iid, "ship it?", ["yes", "no"]))

    r = client.post(
        f"/decisions/{did}/resolve",
        json={"chosen": "yes", "rationale": "looks good", "decided_by": "edo"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"

    row = _run(_read_row(did))
    assert row["status"] == "resolved"
    assert row["payload"].chosen == "yes"
    assert row["payload"].rationale == "looks good"
    assert row["payload"].decided_by == "edo"
    assert row["payload"].resolved_at is not None

    # and it drops off the open feed
    assert client.get(f"/initiatives/{iid}/decisions").json() == []


def test_resolve_guards(client: TestClient, make_initiative: Callable[[], str]):
    iid = make_initiative()
    did = _run(_raise(iid, "ship it?", ["yes", "no"]))
    payload = {"chosen": "yes", "rationale": "r", "decided_by": "edo"}

    # unknown decision -> 404
    assert client.post("/decisions/dec_missing/resolve", json=payload).status_code == 404
    # off-menu choice -> 422
    assert client.post(
        f"/decisions/{did}/resolve", json={**payload, "chosen": "maybe"}
    ).status_code == 422
    # second resolve of the same decision -> 409
    assert client.post(f"/decisions/{did}/resolve", json=payload).status_code == 200
    assert client.post(f"/decisions/{did}/resolve", json=payload).status_code == 409


def test_decisions_survive_redis_flush(
    client: TestClient, make_initiative: Callable[[], str]
):
    # a5 — the cache is derived: a FLUSHALL must not lose decisions or their verdicts.
    iid = make_initiative()
    open_id = _run(_raise(iid, "open one", ["a", "b"]))
    resolved_id = _run(_raise(iid, "resolved one", ["a", "b"]))
    assert client.post(
        f"/decisions/{resolved_id}/resolve",
        json={"chosen": "a", "rationale": "because", "decided_by": "edo"},
    ).status_code == 200

    _run(_flushall())

    # open feed rebuilt straight from Postgres
    feed = client.get(f"/initiatives/{iid}/decisions").json()
    assert [d["id"] for d in feed] == [open_id]
    # and the resolved verdict is intact in the durable row
    row = _run(_read_row(resolved_id))
    assert row["status"] == "resolved"
    assert row["payload"].chosen == "a"
