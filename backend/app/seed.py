"""Seed the `build-doen` initiative and its next-feature spec INTO Doen.

This is the dogfood crossing (spec 0001 / a6): after this runs, Doen holds the
spec for its own next feature, and Claude Code reads it from the running MCP
server instead of from specs/. The next feature is the Steering rail — the human
half of the escalation loop u3 opened.

Idempotent: it never clobbers a spec already in the DB, so re-running after the
human has corrected the draft is safe.

    python -m app.seed
"""

from __future__ import annotations

import asyncio

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, DEV_ORG_ID, DEV_USER_ID, REDIS_URL
from app.store import (
    AcceptanceCriterion,
    Reference,
    Spec,
    SpecItem,
    SpecStore,
    Verify,
)

INITIATIVE_ID = "build-doen"

# A draft authored by the agent at the human's direction — items are proposed, not
# yet confirmed, so they don't bind an executor until the human confirms them
# (which the steering rail itself will let them do).
_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """Close the human half of the escalation loop. After the self-hosting slice (0001) an \
executor can raise a decision and park on wait_for_decision, but the human has nowhere to see or \
answer those escalations — the loop is half-open, and dogfooding stalls the moment an agent needs a \
judgment call.

Build the steering rail: a notification-driven view of an initiative's open decisions, and the \
ability to resolve one — pick an option, give a rationale — which immediately wakes the waiting \
executor. This is the human counterpart to raise_decision / wait_for_decision, and the first real \
instance of the two-surface model from the north-star prototype: the warm, read-only spec document \
on one side, a distinct steering rail on the other. The 0001 spec view stays read-only; the rail is \
the input surface beside it. Resolution is always a human act — agents never resolve their own \
escalations."""

_CONSTRAINTS = [
    "A human issues every verdict — agents never self-resolve a decision they raised (the no-self-approval invariant).",
    "Postgres is the source of truth for decisions; resolving updates the durable row. The Redis escalations stream / pub-sub is derived and must rebuild from Postgres — never store a verdict only in Redis.",
    "Resolving must wake an executor parked on wait_for_decision through the existing Redis pub-sub path (SpecStore.resolve_decision). Do not add a second wake mechanism.",
    "Reuse SpecStore.resolve_decision and the decisions table as-is; do not nest decisions back into the spec document.",
    "No auth in this slice — the single dev user from 0001 still stands (auth is 0007).",
]

_DISCRETION = [
    "The rail's appearance and how it sits beside the read-only spec view.",
    "The live-update transport to the web (SSE, short-polling, or WebSocket).",
    "Endpoint shapes for listing open decisions and for resolving one.",
    "Whether a resolution writes an emitted spec item (emitted_item_ids) now, or that is deferred.",
    "Ordering and grouping of open decisions on the rail.",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("Listing the open decisions for an initiative returns the durable set from Postgres "
     "(id, question, options, recommendation, created_at).", "behavior",
     "GET the open-decisions endpoint for an initiative with open decisions; the response matches the rows."),
    ("Resolving a decision records chosen + rationale + decided_by on the durable row and flips "
     "its status to 'resolved'.", "test",
     "Resolve via the endpoint, then read the decisions row: chosen/rationale/decided_by set, status='resolved'."),
    ("Resolving through the rail wakes an executor blocked on the MCP wait_for_decision tool — the "
     "awaited call returns the resolved decision.", "behavior",
     "Park an MCP wait_for_decision; resolve via the rail; the tool call returns the resolved decision."),
    ("The web shows an initiative's open decisions beside its spec and lets the human resolve one "
     "inline, without leaving the page.", "human_judgment",
     "Load the spec page; an open decision appears on the rail; resolving it updates in place."),
    ("After a Redis flush, the open decisions and their resolved state are rebuilt from Postgres "
     "(the cache is derived).", "test",
     "FLUSHALL Redis, then list/read decisions; results are unchanged."),
]

_REFERENCES = [
    ("code", "backend/app/store.py",
     "raise_decision / resolve_decision / wait_for_decision — reuse as-is."),
    ("code", "backend/app/mcp_server.py",
     "the executor side already calls these tools; the rail is the human counterpart."),
    ("design", "docs/prototypes/living-spec.jsx",
     "north-star for the steering rail and the escalation card."),
    ("doc", "docs/spec-contract.md",
     "the two-surface model and the executor-facing MCP contract."),
    ("prior_initiative", "build-doen/0001-self-hosting-slice",
     "the self-hosting slice; this completes its half-open escalation loop."),
]


def build_spec() -> Spec:
    return Spec(
        initiative_id=INITIATIVE_ID,
        stage="shape",
        title="Steering rail — resolve decisions",
        intent=_INTENT,
        constraints=[SpecItem(text=t, **_DRAFT) for t in _CONSTRAINTS],
        discretion=[SpecItem(text=t, **_DRAFT) for t in _DISCRETION],
        acceptance=[
            AcceptanceCriterion(text=t, verify=Verify(kind=k, detail=d), **_DRAFT)
            for (t, k, d) in _ACCEPTANCE
        ],
        references=[Reference(kind=k, pointer=p, note=n) for (k, p, n) in _REFERENCES],
    )


async def seed() -> None:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pg, redis)
    try:
        await pg.execute(
            """INSERT INTO initiatives (id, org_id, owner_id, appetite, stage)
               VALUES ($1, $2, $3, $4, 'shape')
               ON CONFLICT (id) DO NOTHING""",
            INITIATIVE_ID, DEV_ORG_ID, DEV_USER_ID, "small",
        )
        existing = await store.get_spec(INITIATIVE_ID)
        if existing is not None:
            print(f"spec for '{INITIATIVE_ID}' already present (v{existing.version}); "
                  "leaving it untouched")
            return
        saved = await store.save_spec(build_spec())
        print(f"seeded '{INITIATIVE_ID}' spec v{saved.version}: {saved.title}")
    finally:
        await pg.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(seed())
