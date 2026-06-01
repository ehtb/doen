"""Seed spec 0005 — Memory & the Learn stage — INTO Doen.

Its own initiative_id so it never clobbers 0001-0004 (one spec row per initiative).
The author's spec header said `initiative: build-doen`, but that id belongs to the
shipped Steering-rail spec (0001); reusing it would clobber/no-op. Following the
established `build-doen-000N-name` convention instead.

Items seed as proposed; the human confirms in the UI. The two open shaping decisions
are resolved per the author's recommendations ("go with the recommendations") and
folded into the constraints below — no open decision rows are seeded:
  D1 -> (b) soft gate on advancing to Learn   (constraint 8)
  D2 -> (a) get_context searches decisions + memory only this slice (constraint 9)

Planned decomposition (proposed later via MCP propose_unit during decompose, NOT
seeded here — work units live in their own table, not the spec doc):
  u1 pgvector + embedding infrastructure -> a1, a2, a3
  u2 Learn stage flow                    -> a4, a5
  u3 get_context MCP tool                -> a6, a7, a8

    cd backend && .venv/bin/python -m app.seed_0005
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

INITIATIVE_ID = "build-doen-0005-memory-learn-stage"
TITLE = "Memory & the Learn stage"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """Four initiatives have been completed through Doen and their decisions, constraints, \
and outcomes sit in the database — unembedded, unretrievable, decaying. Every initiative \
completed without memory is one the flywheel doesn't learn from. This spec adds the substrate: \
pgvector for similarity search, embeddings on decisions and completed initiatives, get_context on \
the MCP server so an executor shaping or building the next feature can retrieve relevant prior \
patterns, and a Learn stage that closes the lifecycle — compare outcome to intent, capture what \
was discovered, embed it, and make it available to the future. After this, Doen has \
organizational memory, and it compounds with every initiative completed."""

_CONSTRAINTS = [
    "pgvector is added to Postgres via migration. Embedding columns use the `vector` type with a "
    "configurable dimension (default 1536). No separate vector database — pgvector keeps the "
    "stack minimal.",
    "The embedding provider is pluggable — not hard-coded to any vendor. The hosted tier can wire "
    "a high-quality API provider (Voyage, OpenAI); a self-hoster can swap in a local model or a "
    "different API. The interface is: text in, vector out. A concrete default provider must be "
    "wired for dogfooding.",
    "Embeddings are generated asynchronously. Resolving a decision or completing the Learn stage "
    "triggers embedding generation without blocking the user or the executor. Use the existing "
    "Redis pub/sub or a simple task queue — don't add Celery for this alone.",
    "Memory is append-only. A completed initiative's memory row is never edited — it's a "
    "historical record. New learnings from revisiting become a new row, not an overwrite.",
    "get_context returns source-attributed snippets. Every result carries: which initiative, "
    "which decision or memory entry, the text, and a relevance score. The executor must know "
    "where context came from to judge whether to trust it.",
    "The Learn stage requires a human-written outcome summary. The system can draft or "
    "pre-populate from the spec + decisions, but the human confirms — this is a judgment act, "
    "not an automated close.",
    "No auth this slice — single dev user.",
    "Advancing to the Learn stage is soft-gated: if work units are incomplete, warn clearly "
    "(e.g. \"3 of 5 units are not yet verified — advance anyway?\") but allow the move. "
    "Incomplete initiatives still carry learnings worth capturing, so the gate never blocks "
    "entry to Learn (D1 resolved -> b: soft gate).",
    "get_context searches the decisions + memory tables only this slice — they capture the "
    "reasoning and outcomes, the highest-value context. Cross-initiative search of confirmed "
    "spec items (constraints / intent) is deferred to a follow-up to keep embedding scope narrow "
    "and ship faster (D2 resolved -> a: decisions + memory only).",
]

_DISCRETION = [
    "Embedding model and dimension for the dogfooding default provider.",
    "Background task mechanism (Redis pub/sub listener, asyncio task queue, or inline-async with "
    "a fire-and-forget pattern — pick the lightest that works).",
    "How the Learn UI presents the initiative's history for review (timeline, summary, or just "
    "the raw intent + decisions + unit outcomes side by side).",
    "How many results get_context returns and whether to expose a relevance threshold.",
    "Whether to pre-populate the outcome summary from the spec's intent + acceptance criteria as "
    "a draft the human corrects (recommended — correction over authoring) or start blank.",
    "Index type for pgvector (IVFFlat vs HNSW) — at this scale either is fine.",
    "Whether the backfill of existing decisions runs as a one-time migration script or a "
    "management command.",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("pgvector extension is active; the decisions table has an embedding vector column; a memory "
     "table exists with id, initiative_id, summary, learnings, outcome, embedding, created_at.",
     "test",
     "Assert the vector extension is installed, decisions.embedding exists, and the memory table "
     "has all named columns."),
    ("Resolving a decision triggers async embedding generation; the decision row's embedding "
     "column is populated within a reasonable window (seconds, not minutes).", "test",
     "Resolve a decision; poll the row; assert embedding is non-null within a short window."),
    ("Existing resolved decisions from previous initiatives are backfilled with embeddings. No "
     "resolved decision has a null embedding after the backfill.", "test",
     "Run the backfill; assert the count of resolved decisions with a null embedding is 0."),
    ("Advancing an initiative to the Learn stage shows: the original intent, the decisions made "
     "(with chosen options and rationale), and the verification outcomes per unit — enough "
     "context for the human to judge what happened vs. what was intended.", "behavior",
     "Advance an initiative to Learn; the page shows intent, resolved decisions, and per-unit "
     "verdicts side by side."),
    ("The human submits an outcome summary and learnings; a memory row is created, embedded, and "
     "the initiative is marked complete (stage = learn, done).", "behavior",
     "Submit the Learn form; a memory row exists with an embedding and the initiative sits at "
     "stage=learn."),
    ("get_context(initiative_id, query) on the MCP server returns relevant snippets from the "
     "decisions and memory tables, with source attribution (initiative, type, text, score).",
     "behavior",
     "Call get_context with a query; results carry initiative, type, text, and a relevance "
     "score."),
    ("get_context retrieves results from other initiatives' completed memory — not just the "
     "current one. Cross-initiative retrieval works.", "test",
     "Seed memory on initiative A; query get_context scoped from initiative B; assert A's memory "
     "is returned."),
    ("While shaping a new initiative (or building one), an executor calls get_context and receives "
     "relevant patterns, decisions, and learnings from previously completed initiatives — the "
     "agent has organizational memory that makes the current work better informed. [HEADLINE]",
     "human_judgment",
     "Complete an initiative through Learn, then from a new initiative call get_context and judge "
     "the relevance of the returned prior patterns, decisions, and learnings."),
]

_REFERENCES = [
    ("code", "backend/app/store.py",
     "decisions.embedding + the memory table are already sketched in the store docstring; add the "
     "embedding provider, async embed, memory ops, and get_context here."),
    ("code", "backend/app/mcp_server.py",
     "executor-facing MCP tools — add get_context (similarity search over decisions + memory) here."),
    ("prior_initiative", "build-doen-0003-work-units-verification",
     "resolved decisions + per-unit verdicts are the corpus the Learn stage summarizes and embeds."),
    ("prior_initiative", "build-doen-0004-initiative-lifecycle",
     "stage progression — Learn is the terminal lifecycle stage this spec closes."),
    ("doc", "docs/spec-contract.md",
     "the lifecycle stages and the learn->shape flywheel this memory substrate feeds."),
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
