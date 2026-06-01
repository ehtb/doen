"""u5 — the enriched MCP surface (spec 0013 / build-doen).

Covers a8/a9 (item_7f2c52726965, item_e0ff02e3f8d4): get_conversation_summary returns the key
decisions (with the chosen option), the rejected alternatives, and the human's stated priorities;
and get_spec's enrichment exposes the Advisor's latest note + per-unit context (submission,
verdict/feedback, Advisor review notes). Deterministic — no model call — so the suite stays
offline. Integration tests over the real docker-compose Postgres + Redis.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from fastapi.testclient import TestClient
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.models import CriterionResult, Decision, Submission, WorkUnit
from app.services.conversation import spec_enrichment, summarize_conversation
from app.store import SpecStore


def _store_run(fn: Callable[[SpecStore], Awaitable[object]]) -> object:
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis))
        finally:
            await pg.close()
            await redis.aclose()

    return asyncio.run(go())


# --- e0ff: the conversation summary covers the durable decision reasoning ------------
def test_conversation_summary_covers_decisions_and_alternatives(
    client: TestClient, make_initiative: Callable[[], str]
):
    # Conversations are browser-local now (spec uvama, decision dec_0397d7a8f45e/A): the human's
    # stated_priorities came from message turns the backend can no longer read, so they degrade to
    # an empty list. The durable reasoning — resolved decisions + their rejected alternatives —
    # is unaffected, and that is what the summary still carries.
    iid = make_initiative()

    def seed(store: SpecStore):
        async def go():
            # a decision is raised and resolved (a key decision with rejected options)
            d = await store.raise_decision(
                Decision(
                    question="Which CSV text encoding?",
                    options=["UTF-8", "UTF-16", "Latin-1"],
                    recommendation="UTF-8",
                ),
                iid,
            )
            await store.resolve_decision(
                d.id, "UTF-8", "Widest compatibility; the report is ASCII-heavy.", "Edo Balvers"
            )
            return await summarize_conversation(store, iid)

        return go()

    summary = _store_run(seed)
    assert summary["initiative_id"] == iid

    # at least one key decision, carrying the option chosen
    chosen = [k for k in summary["key_decisions"] if k["chosen"] == "UTF-8"]
    assert chosen, "no key decision with a chosen option"
    assert chosen[0]["rationale"]  # the reasoning behind it is carried too

    # at least one rejected alternative
    rejected = {alt for r in summary["rejected_alternatives"] for alt in r["alternatives"]}
    assert {"UTF-16", "Latin-1"} <= rejected, f"rejected alternatives missing: {rejected}"

    # stated_priorities is browser-local now — the backend reports it empty (not crash)
    assert summary["stated_priorities"] == []


def test_conversation_summary_unknown_initiative_raises(
    client: TestClient,
):
    from app.exceptions import NotFoundError

    def go(store: SpecStore):
        return summarize_conversation(store, "no-such-initiative")

    with pytest.raises(NotFoundError):
        _store_run(go)


# --- 7f2c: get_spec enrichment — durable per-unit context ----------------------------
def test_spec_enrichment_unit_context(
    client: TestClient, make_initiative: Callable[[], str]
):
    # The message-derived fields (advisor_summary, per-unit advisor_review) are browser-local now
    # (spec uvama, decision dec_0397d7a8f45e/A): advisor_summary is always None and advisor_review
    # is gone. What remains is the durable work-unit context — submission summary + the human's
    # verdict and feedback.
    iid = make_initiative()

    def seed(store: SpecStore):
        async def go():
            unit = await store.create_unit(
                WorkUnit(spec_id=iid, title="Stream the export", scope="...", criterion_ids=[])
            )
            await store.confirm_unit(unit.id)  # proposed -> ready
            await store.claim_unit(unit.id)  # ready -> in_progress
            await store.submit_for_verification(
                unit.id,
                Submission(
                    summary="Streams rows in constant memory.",
                    criteria_results=[
                        CriterionResult(criterion_id="x", result="pass", evidence="capped-heap run")
                    ],
                ),
            )  # in_progress -> in_verification
            await store.record_verdict(unit.id, "approved", "Ship it.", "Edo Balvers")  # -> done
            return unit.id, await spec_enrichment(store, iid)

        return go()

    unit_id, enr = _store_run(seed)
    assert enr["advisor_summary"] is None  # browser-local now — no server-side advisor note
    uc = enr["unit_context"][unit_id]
    assert uc["submission_summary"] == "Streams rows in constant memory."
    assert uc["verdict"] == "approved"
    assert uc["verification_feedback"] == "Ship it."
    assert "advisor_review" not in uc  # the per-unit Advisor review was retired with messages
