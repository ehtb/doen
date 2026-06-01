"""Seed spec 0003 — Work units & verification — INTO Doen.

Its own initiative_id so it never clobbers the 0001/0002 specs (one spec row per
initiative). Items seed as proposed, not confirmed, so they don't bind an executor
until the human confirms them in the UI — dogfooding the 0002 confirm flow.

D1 resolved (c): the executor *proposes* units (status=proposed); a human confirms
them to ready before they're workable. That fold-in lives in constraint 2, a1, the
confirm criterion, and constraint 5 (no self-confirm).

Idempotent: never clobbers a spec already in the DB.

    cd backend && .venv/bin/python -m app.seed_0003
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

INITIATIVE_ID = "build-doen-0003-work-units-verification"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """The shape->decide loop runs through Doen; the build->verify loop still lives in the \
terminal. An executor reads the spec and raises decisions through the app, but picks up work, \
reports progress, and hands it back informally — outside the system. Work units and verification \
close that gap: decompose a spec into tracked, bounded units the executor claims via MCP, builds \
against, and submits back with per-criterion evidence for the human to judge. After this, the \
entire lifecycle — shape, decompose, implement, verify — runs through Doen."""

_CONSTRAINTS = [
    "Work units are their own table, not inside the spec JSONB. Units change at a different "
    "frequency than the spec (progress heartbeats, status transitions); sharing the spec's "
    "version lock would let an agent reporting progress 409 a human editing a constraint. "
    "Separate concerns, separate storage. Table keyed to spec_id.",
    "Status transitions follow a fixed state machine: "
    "proposed -> ready -> in_progress -> blocked_on_decision -> in_verification -> done, plus "
    "changes_requested -> in_progress on a failed verification. Units are created proposed; a "
    "human confirms them to ready before they are workable. No skipping states; no backward "
    "transitions except changes_requested.",
    "blocked_on_decision links to a decision id. Resolving the decision moves the unit to "
    "in_progress automatically (or the executor re-reads and resumes).",
    "submit_for_verification requires the executor to map its output to each acceptance "
    "criterion the unit satisfies, with a result per criterion (pass / fail / needs_judgment) "
    "and evidence. The human judges intent-alignment, not code.",
    "An executor cannot set its own verdict, and cannot confirm its own proposed unit. "
    "get_verification only returns a verdict a human gave; there is no self-approval path — "
    "this is the product.",
    "No auth this slice — single dev user (auth is 0007).",
    "Reuse existing models, SpecStore, and the Redis cache/pub-sub patterns from the escalation "
    "loop (0001), and the proposed->confirmed provenance pattern from 0002.",
]

_DISCRETION = [
    "Table schema details beyond the fields specified (indexes, column types).",
    "Whether report_progress writes to Redis (ephemeral) or Postgres (durable) — the heartbeat "
    "is lightweight and either is fine for this slice.",
    "UI layout for the units view: inline on the spec page or a separate tab/section, and where "
    "the confirm-unit action lives.",
    "How changes_requested feedback is presented to the executor (a text field is fine).",
    "How evidence is structured (free-form JSON or a typed schema) — keep it simple.",
    "Whether to show a minimal progress indicator per unit or just status labels.",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("A work unit can be created with a spec_id, title, scope, and a list of acceptance "
     "criterion ids it satisfies, persisting to the work_units table as status=proposed.",
     "test",
     "Create a unit via the store; read the row back: fields persisted, status='proposed'."),
    ("Status transitions follow the state machine exactly; an invalid transition "
     "(e.g. ready -> done, or proposed -> in_progress) is rejected.", "test",
     "Drive valid transitions through; assert each illegal jump raises."),
    ("propose_unit (executor) drafts a unit as proposed, and list_units(spec_id, status?) on "
     "the MCP server returns units for a spec, optionally filtered by status.", "behavior",
     "propose_unit then list_units with and without a status filter; the proposed unit appears."),
    ("A human confirms a proposed unit to ready — the only path to workable. The executor has "
     "no confirm path (no-self-confirm).", "test",
     "Confirm via the human endpoint: proposed -> ready. There is no MCP tool that confirms."),
    ("report_progress(unit_id, note) updates the unit's progress note; the spec view reflects "
     "it.", "behavior",
     "Call report_progress; the note shows on the unit in the UI / on read."),
    ("submit_for_verification(unit_id, summary, criteria_results, artifacts) moves the unit to "
     "in_verification and persists the submission. Requires at least one criterion result.",
     "test",
     "Submit with one criterion result -> in_verification, submission stored. Empty results is "
     "rejected."),
    ("A human verdict of approved moves the unit to done; changes_requested moves it to "
     "in_progress with feedback attached. No other verdict source exists.", "test",
     "approved -> done; changes_requested -> in_progress with feedback on the row."),
    ("get_verification(unit_id) returns the verdict and feedback, or pending if not yet "
     "judged.", "behavior",
     "Before a verdict: pending. After: the verdict + feedback."),
    ("A unit in blocked_on_decision links to a decision id; resolving that decision via the "
     "existing escalation flow transitions the unit to in_progress.", "test",
     "Block a unit on a decision, resolve via the rail, assert the unit moved to in_progress."),
    ("From the spec view, a human can confirm proposed units, see submitted units with their "
     "per-criterion evidence, approve or request changes, and the executor sees the verdict via "
     "MCP — the full decompose->verify loop closes inside Doen. [HEADLINE]", "human_judgment",
     "Walk the loop end to end in the UI: propose (MCP) -> confirm -> work -> submit -> judge -> "
     "executor reads the verdict via get_verification."),
]

_REFERENCES = [
    ("code", "backend/app/store.py",
     "SpecStore, the work_units heartbeat stub, and the decisions / pub-sub patterns to reuse."),
    ("code", "backend/app/mcp_server.py",
     "executor-facing MCP tools — add propose_unit / list_units / report_progress / "
     "submit_for_verification / get_verification here."),
    ("prior_initiative", "build-doen-0002-spec-editing",
     "the proposed->confirmed provenance model this reuses for unit confirmation."),
    ("doc", "docs/spec-contract.md",
     "the lifecycle and the executor-facing MCP contract."),
]


def build_spec() -> Spec:
    return Spec(
        initiative_id=INITIATIVE_ID,
        stage="shape",
        title="Work units & verification",
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
