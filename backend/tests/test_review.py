"""u5 — verify review (a7) + learn draft (a8), spec 0009.

a7: the Advisor weighs a submitted unit's evidence against each acceptance criterion and the
notes land on the rail (auto-posted on submit in the MCP tool; here we drive the service
directly). a8: the Advisor drafts a learn-stage outcome from the initiative's history for the
human to correct. LLM faked (branches on schema_name); embedder faked. Needs PG + Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.models import (
    AcceptanceCriterion,
    CriterionResult,
    Decision,
    SpecItem,
    Submission,
    Verify,
    WorkUnit,
)
from app.services.learn import draft_outcome
from app.services.review import post_review, review_submission
from app.store import SpecStore

DIM = 1536

REVIEW_PAYLOAD = {
    "summary": "Solid overall — the kill-consumer test is the right probe for the durability bar.",
    "criteria": [
        {
            "criterion": "A failed delivery is retried and never lost.",
            "assessment": "aligned",
            "note": "the redelivery test exercises a mid-flight crash and asserts re-delivery.",
        }
    ],
    "concerns": ["No evidence the backoff is capped — an unbounded retry could hammer the consumer."],
}

OUTCOME_PAYLOAD = {
    "summary": "Shipped a Postgres-backed retry queue with backoff; the durability unit verified.",
    "learnings": "Lease-based reclaim beats naive retries for at-least-once delivery.",
}


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        return OUTCOME_PAYLOAD if schema_name == "outcome" else REVIEW_PAYLOAD


class FakeEmbedder:
    dimension = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


def _store_run(
    fn: Callable[[SpecStore], Awaitable[object]], embedder: FakeEmbedder | None = None
) -> object:
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis, embedder=embedder))
        finally:
            await pg.close()
            await redis.aclose()

    return asyncio.run(go())


async def _submit_unit(store: SpecStore, iid: str) -> str:
    """Drive a unit all the way to in_verification with a submission, so it can be reviewed."""
    spec = await store.get_spec(iid)
    assert spec is not None
    spec.constraints.append(
        SpecItem(text="No third-party queue — reuse Postgres + Redis.", provenance="human", status="confirmed")
    )
    crit = AcceptanceCriterion(
        text="A failed delivery is retried and never lost.",
        verify=Verify(kind="test", detail="kill the consumer mid-delivery; assert redelivery"),
        provenance="human", status="confirmed",
    )
    spec.acceptance.append(crit)
    await store.save_spec(spec)
    unit = await store.create_unit(
        WorkUnit(spec_id=iid, title="retry scheduler", scope="re-enqueues failed deliveries with backoff",
                 criterion_ids=[crit.id])
    )
    await store.confirm_unit(unit.id)  # proposed -> ready
    await store.claim_unit(unit.id)    # ready -> in_progress
    await store.submit_for_verification(
        unit.id,
        Submission(
            summary="Added a Postgres-backed retry queue with exponential backoff.",
            criteria_results=[
                CriterionResult(
                    criterion_id=crit.id, result="pass",
                    evidence="a test kills the consumer mid-delivery and asserts redelivery",
                )
            ],
            artifacts=["backend/app/retry.py"],
        ),
    )
    return unit.id


# --- a7: the Advisor reviews evidence against each criterion ------------------
def test_review_weighs_evidence_against_criteria(make_initiative: Callable[[], str]):
    iid = make_initiative()
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            uid = await _submit_unit(store, iid)
            return await review_submission(store, uid, llm=fake)

        return inner()

    notes = _store_run(go, embedder=FakeEmbedder())
    assert notes.summary
    assert notes.criteria[0].assessment == "aligned"
    assert notes.concerns  # cross-cutting concern surfaced
    # a7 — the criterion AND the executor's evidence were put in front of the Advisor
    user = fake.calls[0]["user"]
    assert "retried and never lost" in user and "redelivery" in user
    assert "must not be crossed" in user.lower() or "Postgres + Redis" in user  # constraints fed in
    assert fake.calls[0]["schema_name"] == "review"


# --- a7 / D1->b: the review lands on the rail as an advisor message -----------
def test_review_is_posted_to_the_rail(make_initiative: Callable[[], str]):
    iid = make_initiative()
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            uid = await _submit_unit(store, iid)
            notes = await post_review(store, uid, llm=fake)
            msgs = await store.list_messages(iid)
            return notes, msgs

        return inner()

    notes, msgs = _store_run(go, embedder=FakeEmbedder())
    advisor = [m for m in msgs if m.role == "advisor"]
    assert advisor, "the review did not land on the rail"
    last = advisor[-1]
    assert "Preliminary review" in last.content and "retry scheduler" in last.content
    assert "verdict is yours" in last.content  # it's notes, not a verdict (no self-approval)
    assert last.metadata.get("review", {}).get("unit_id") == notes.unit_id  # structured notes attached


# --- a8: the Advisor drafts an outcome from the initiative's history ----------
def test_draft_outcome_from_history(make_initiative: Callable[[], str]):
    iid = make_initiative()
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            spec = await store.get_spec(iid)
            assert spec is not None
            spec.intent = "Deliver webhooks reliably, at least once, without a third-party queue."
            await store.save_spec(spec)
            d = await store.raise_decision(
                Decision(question="at-least-once or exactly-once delivery?",
                         options=["at-least-once", "exactly-once"]),
                iid,
            )
            await store.resolve_decision(d.id, "at-least-once", "exactly-once is impractical here", "edo")
            await store._drain()
            return await draft_outcome(store, iid, llm=fake)

        return inner()

    draft = _store_run(go, embedder=FakeEmbedder())
    assert draft.summary == OUTCOME_PAYLOAD["summary"]
    assert draft.learnings == OUTCOME_PAYLOAD["learnings"]
    # a8 — the history (intent + the resolved decision) was fed to the Advisor
    user = fake.calls[0]["user"]
    assert "Deliver webhooks reliably" in user
    assert "at-least-once or exactly-once" in user and "exactly-once is impractical" in user
    assert fake.calls[0]["schema_name"] == "outcome"
