"""Seed spec 0004 — Initiative lifecycle management — INTO Doen.

Its own initiative_id so it never clobbers 0001-0003. Items seed as proposed; the
human confirms in the UI. D1 resolved (a): the MCP get_spec response carries the
initiative's {id, title, stage} — folded into the constraints below.

    cd backend && .venv/bin/python -m app.seed_0004
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

INITIATIVE_ID = "build-doen-0004-initiative-lifecycle"
TITLE = "Initiative lifecycle management"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """The loop works — shape, decompose, implement, verify all run through Doen. But every \
initiative is an island accessed by a URL you have to know, seeded by a Python script you have to \
run, and the `stage` field on every spec is decoration that nothing tracks. This spec adds the \
structural layer that makes the app navigable and self-sufficient: a home listing all initiatives \
with their lifecycle stage, a way to create one from inside the app (no seed scripts, no files), \
and stage progression that makes the lifecycle visible and enforced. After this, the daily \
workflow is: open Doen, create an initiative, shape its spec, build it — nothing outside the app."""

_CONSTRAINTS = [
    "`initiatives` is the parent entity. Specs, decisions, and work units all belong to an "
    "initiative. Schema at minimum: id (slug, PK), title, org_id, owner_id (nullable for now), "
    "stage, created_at, updated_at.",
    "Creating an initiative scaffolds an empty spec in one act — the two are born together. "
    "The spec starts at stage=discover, version 0, with empty item lists.",
    "Stage transitions follow the lifecycle order: discover -> shape -> bet -> decompose -> "
    "implement -> verify -> learn. No skipping stages. Backward movement is allowed only to the "
    "immediately prior stage (rework), not arbitrary jumps.",
    "The dashboard is the app's home and entry point — the first thing you see at /. Every "
    "initiative is reachable from it.",
    "Migration must create initiative rows for existing specs (build-doen, 0002, 0003, etc.) so "
    "nothing is lost. Derive the title from the existing spec title; infer stage from current state.",
    "No auth this slice — single dev user. org_id and owner_id exist on the table but are "
    "nullable / unused until 0007.",
    "The initiative id is a slug (kebab-case from the title, e.g. passwordless-sign-in), enforced "
    "unique. Slugs are human-readable in URLs and MCP calls — this matters for a human tool.",
    "MCP get_spec returns the initiative's {id, title, stage} alongside the spec, so an executor "
    "grounds itself in lifecycle context in one call (D1 resolved -> option a: enrich get_spec).",
]

_DISCRETION = [
    "Dashboard layout, density, and what metadata to show per initiative (stage, unit counts, "
    "last-updated, open decisions — pick what's useful, skip what's clutter).",
    "How stage transitions are triggered in the UI (button, dropdown, inline control).",
    "Whether advancing to implement requires at least one confirmed work unit, or is purely "
    "manual. A soft gate is fine; a hard gate may be premature.",
    "Whether to show a visual lifecycle stepper on the initiative/spec page (reuse the prototype "
    "idea if it fits; skip if it's overhead now).",
    "URL structure beyond the slug (/initiatives/:slug, /i/:slug, or keep /specs/:id and redirect).",
    "Slug collision handling (reject, append suffix, or prompt the user).",
    "How the create-initiative flow is presented (modal, separate page, inline on dashboard).",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("Creating an initiative persists a row in the initiatives table and scaffolds an empty spec "
     "(version 0, stage=discover, all item lists empty) in specs.", "test",
     "Create via the store; assert the initiative row and a v0/discover empty spec both exist."),
    ("The slug is derived from the title (kebab-case), enforced unique; a duplicate title is "
     "handled without error (reject or disambiguate).", "test",
     "Create two initiatives with the same title; both succeed with distinct unique slugs."),
    ("The dashboard at / lists all initiatives with their title, current stage, and a link to "
     "their spec. Existing migrated initiatives appear.", "behavior",
     "Load /; every initiative (including migrated 0001-0003) is listed with stage + a spec link."),
    ("Stage transitions follow the defined order; an invalid transition (e.g. discover -> "
     "implement) is rejected.", "test",
     "Drive valid steps; assert a skip and an arbitrary backward jump both raise."),
    ("A human can advance or retreat (one step back) an initiative's stage from the UI; the "
     "spec's stage field updates to match.", "behavior",
     "Advance then retreat from the UI; the initiative row and the spec doc stage stay in sync."),
    ("Migration creates initiative rows for all existing specs, with titles and stages inferred. "
     "No existing spec is orphaned.", "test",
     "After the migration, every spec's initiative has a title and a stage matching the spec."),
    ("From /, a human creates a new initiative, lands in its empty spec, shapes it by adding items "
     "(via 0002's editing), and an executor reads it via MCP — the full authoring flow starts and "
     "ends inside Doen, no seed script. [HEADLINE]", "human_judgment",
     "Walk it end to end in the UI: create from / -> empty spec -> add items -> get_spec over MCP."),
]

_REFERENCES = [
    ("code", "backend/app/store.py",
     "SpecStore + the initiatives table; add create_initiative / get_initiative / list_initiatives."),
    ("code", "backend/app/mcp_server.py",
     "get_spec is enriched with the initiative's {id, title, stage} (D1)."),
    ("design", "docs/prototypes/living-spec.jsx",
     "the lifecycle stepper idea, reusable on the dashboard / spec page."),
    ("prior_initiative", "build-doen-0003-work-units-verification",
     "work units inform the soft gate for advancing to implement."),
    ("doc", "docs/spec-contract.md", "the lifecycle stages and the executor-facing MCP contract."),
]


def build_spec() -> Spec:
    return Spec(
        initiative_id=INITIATIVE_ID,
        stage="shape",
        title=TITLE,
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
            """INSERT INTO initiatives (id, org_id, owner_id, appetite, stage, title)
               VALUES ($1, $2, $3, $4, 'shape', $5)
               ON CONFLICT (id) DO NOTHING""",
            INITIATIVE_ID, DEV_ORG_ID, DEV_USER_ID, "small", TITLE,
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
