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
  Layered (see "Backend architecture" below) — don't put business logic or data access in routers.
- **Store:** Postgres = source of truth. Redis = derived hot cache + real-time coordination.
- **Data layer:** `backend/app/store.py` — the `SpecStore` repository. Domain models live in
  `app/models.py`. Reuse them; don't reinvent.
- **Web:** Next.js (App Router), TypeScript, Tailwind, shadcn/ui, shadcn/ui-prose, Tailwind Typography.
- **Integration:** an MCP server exposing the spec tools so executors read/write the spec.
- **Deps + tooling:** `backend/pyproject.toml` (hatchling); pyright type-checks `app/`.
- Shipped since: pgvector memory + `get_context` (0005), AI-assisted shaping (0006), the
  one-command Docker setup (0008). Still later: WorkOS AuthKit (0007), the conversation rail.

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
├── CLAUDE.md                 # this file (the constitution)
├── docker-compose.yml        # full stack: pgvector Postgres, Redis, backend, web
├── docs/                     # spec-contract.md, design-principles.md, getting-started.md
├── specs/                    # historical bootstrap specs (new specs live IN Doen now)
├── backend/app/
│   ├── main.py               # app factory: lifespan, exception handlers, routers
│   ├── config.py / database.py   # settings; shared pool/redis + the FastAPI deps
│   ├── models.py             # domain models (the spec contract as Pydantic)
│   ├── schemas.py            # API request/response models
│   ├── exceptions.py         # domain errors + the HTTP error-mapping handlers
│   ├── store.py              # SpecStore — the repository (all Postgres/Redis access)
│   ├── services/             # business logic: shaping, authoring, learn, decisions
│   ├── providers/            # external integrations: llm, embeddings (pluggable)
│   ├── routers/              # thin APIRouters per domain
│   ├── mcp_server.py         # the executor-facing MCP tools (stdio)
│   └── migrate.py / backfill_embeddings.py   # ops
└── web/app/…                 # Next.js: dashboard, living-spec view, steering rail
```

## Backend architecture — layered (FastAPI best-practice)

A request flows **router → service → repository**, over shared **models / schemas / providers /
exceptions**. Keep each concern in its layer — the cardinal sin is business logic or SQL in a
router.

- **routers/** — one `APIRouter` per domain. Thin: read the request, call a service or the
  store, return. No business logic, and **no try/except** — domain exceptions are mapped to
  status codes centrally (see exceptions).
- **services/** — business logic / orchestration (shaping, authoring, learn, decisions).
  **Framework-agnostic**: they never import FastAPI, so they're testable without the web layer
  and reusable from the MCP server. They raise domain exceptions.
- **store.py** — the `SpecStore` **repository**: the *only* place that touches Postgres/Redis.
- **models.py** = durable **domain** models; **schemas.py** = the **API** request/response
  shapes. Keep them separate — the wire format is not the domain.
- **providers/** — external integrations behind a tiny interface (LLM, embeddings), pluggable by
  config so a self-hoster can swap vendors. API keys come from env, never the DB.
- **exceptions.py** — domain errors (`NotFoundError`→404, `ValidationError` & the transition
  errors→422, `ConflictError`/stale-version→409, `LLMError`→502) **and** the single place that
  maps them to HTTP, via `register_exception_handlers(app)`. This is the error "middleware".

Decisions baked in: thin routers + one central place for error mapping (never repeat try/except
per route); services don't depend on the framework; one repository owns all data access; the
domain model is not the API schema; external vendors sit behind pluggable providers keyed from
env. The same domain exceptions are what the MCP server surfaces as tool errors.

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
