# Doen — Project Context for Claude Code

> Read this first, every session. It is the constitution. A spec governs the work;
> this file governs how you work on any spec.

## What Doen is

Doen is the **intent layer** above agentic executors. Humans author and steer a _living spec_
for an initiative; executors (you, Claude Code) build against it and surface decisions back.
Doen is not where code gets written by hand — it's where you decide what's worth building and
verify it was built right. The canonical design lives in @docs/spec-contract.md.

## Stack

- **Backend:** FastAPI, async throughout. `asyncpg` (no ORM — keep overhead low). Pydantic v2.
- **Store:** Postgres = source of truth. Redis = derived hot cache + real-time coordination.
- **Data layer:** already written — `backend/app/store.py` (models + `SpecStore`). Reuse it; do
  not reinvent it.
- **Web:** Next.js (App Router), TypeScript.
- **Integration:** an MCP server exposing the spec tools so executors read/write the spec.
- Later specs add: pgvector (memory + drift), WorkOS AuthKit, the conversation rail. Not now.

## Architecture invariants — hard constraints, never cross

1. **Postgres is the only source of truth.** Redis is derived and must always be rebuildable
   from Postgres. Nothing durable lives only in Redis (heartbeats/locks excepted — they're
   deliberately ephemeral).
2. **The spec is one JSONB document** — one row per initiative. Do NOT normalise it into
   per-item tables.
3. **Decisions are durable rows** in their own table, not nested in the spec doc.
4. **`version` is an optimistic lock.** Never bypass the stale-version check on write.
5. **No estimation anywhere** — no story points, no hours, no velocity. Ever.
6. **You never self-approve work.** Verification is queued for user approval; only he issues a verdict.

## Repo layout

```
doen/
├── CLAUDE.md                 # this file
├── docker-compose.yml        # local postgres + redis
├── docs/spec-contract.md     # canonical architecture
├── specs/                    # bootstrap specs live here UNTIL Doen can hold its own
├── backend/app/{main,store,routes,mcp}/…
└── web/app/…
```

## How we work

- **Why these rules, and what we've rejected:** consult docs/design-principles.md before
  proposing design or architecture changes — it records the rationale and the paths we
  deliberately chose not to take.
- **Spec-driven.** Build only what the active spec covers. Out-of-scope ideas become a note,
  not code. During bootstrap the active spec is in `specs/`; after the dogfood milestone it
  lives inside Doen and you fetch it via MCP.
- **Governing principle:** act within the constraints, decide freely within the discretion,
  **escalate everything else that is a product or intent call.** Do not guess on intent.
- **Surfacing a decision (bootstrap):** when you hit a call outside constraints + discretion,
  append it to the active spec's `## Decisions (open)` section — numbered, with context,
  options, and your recommendation — then STOP and ask the user in the session. Resolving it in
  code is the one unforgivable move.
- **Self-verify before handing off.** Check each acceptance criterion explicitly and report
  pass / fail / needs-judgment with evidence. Then let the user verify intent-alignment.
- **Small commits.** One work unit per commit; reference the unit in the message.

## The dogfood milestone — the north star for everything before it

> Doen stores the spec for its own next feature, and Claude Code builds that feature by
> reading the spec from the **running Doen MCP server**, not from `specs/`.

Everything in `specs/0001` exists to reach this line as fast as possible. The moment you cross
it, specs move into Doen and we are dogfooding. Cut anything that doesn't serve it.
