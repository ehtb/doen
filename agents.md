<!-- last-reviewed: 2026-05-30 after spec BD-14 -->
# Doen — Project Context for Claude Code

> Read this first, every session. It is the constitution. A spec governs the work;
> this file governs how you work on any spec.

## What Doen is

Doen is the **intent layer** above agentic executors. Humans author and steer a _living spec_
for an initiative; executors (you, Claude Code) build against it and surface decisions back.
Doen is not where code gets written by hand — it's where you decide what's worth building and
verify it was built right. The contract you work against lives in @docs/spec-contract.md.
The rationale behind every architectural call — and the paths we deliberately rejected — lives
in @docs/design-principles.md.

## Stack

- **Backend:** FastAPI, async throughout. `asyncpg` (no ORM — keep overhead low). Pydantic v2.
  Layered (router → service → repository) — don't put business logic or data access in routers.
- **Store:** Postgres = source of truth (including conversation history in the `messages`
  table). Redis = derived hot cache + real-time coordination (decision pub/sub).
- **Data layer:** `backend/app/store.py` — the `SpecStore` repository. Domain models live in
  `backend/app/models.py`. Reuse them; don't reinvent.
- **Web:** Next.js (App Router), TypeScript, Tailwind, shadcn/ui, Tailwind Typography.
- **Integration:** an MCP server (stdio for self-hosted; Streamable HTTP for hosted) exposing
  the spec tools so executors read and write the spec.
- **Deps + tooling:** `backend/pyproject.toml` (hatchling); pyright type-checks `app/`.

## Architecture invariants — hard constraints, never cross

1. **Postgres is the only source of truth.** Redis is derived and must always be rebuildable
   from Postgres. Nothing durable lives only in Redis (heartbeats / locks excepted — they're
   deliberately ephemeral).
2. **The spec is one JSONB document** — one row per initiative. Do NOT normalise spec items
   into per-item tables. Work units and decisions are separate tables; spec items are not.
3. **Decisions are durable rows** in their own table, not nested in the spec doc.
4. **Every initiative belongs to a project.** `project_id` is required — there are no orphan
   specs.
5. **`version` is an optimistic lock.** Never bypass the stale-version check on write.
6. **No estimation anywhere** — no story points, no hours, no velocity. Ever.
7. **State is derived, not stored.** Initiative lifecycle (draft / building / complete) is
   computed from work units + the learn record. There is no manual advance.
8. **You never self-approve work.** Verification is queued for the human; only they issue a
   verdict. The same applies to confirming your own proposed unit.

## How we work

- **Why these rules, and what we've rejected:** consult `docs/design-principles.md` before
  proposing design or architecture changes — it records the rationale and the paths we
  deliberately chose not to take.
- **Spec-driven.** Build only what the active spec covers. Out-of-scope ideas become a note,
  not code. Specs live IN Doen — fetch via `get_spec` from the running MCP server.
- **Ground in the why, not just the what.** Pair `get_spec` with `get_conversation_summary`
  — the former tells you what to build, the latter tells you the resolved decisions, rejected
  alternatives, and stated priorities behind it. Don't re-decide what's settled.
- **Governing principle:** act within the constraints, decide freely within the discretion,
  **escalate everything else that is a product or intent call.** Do not guess on intent.
- **Surfacing a decision:** when you hit a call outside constraints + discretion, call
  `raise_decision` (optionally with `unit_id` to park the unit on it). Then STOP. Resolving an
  intent question in code is the one unforgivable move.
- **Self-verify before handing off.** Check each acceptance criterion explicitly and report
  pass / fail / needs-judgment with evidence via `submit_for_verification`. The human judges
  intent-alignment, not your diff line-by-line.
- **Small commits.** One work unit per commit; reference the unit in the message.

## Keeping these docs current

> Any spec that changes architecture, conventions, or the MCP surface must update agents.md, spec-contract.md, and/or design-principles.md as part of its acceptance criteria.

That sentence is binding — doc updates ride along with the spec that caused them, never
deferred to a follow-up. Review cadence: every ~5 specs, or immediately after any spec that
touches architecture, conventions, or the MCP surface. Run the `/sync-docs` skill
(`.claude/skills/sync-docs/SKILL.md`) on demand to audit drift between these three docs and
the codebase — and to surface proposed updates back to a human for confirmation.

## Current state — volatile; expect drift fastest here

### Lifecycle (initiative state)
Three derived states, computed by `derive_state()` in `backend/app/models.py`:
- **draft** — no units yet, or all units are still `proposed` / `ready`. The spec can still be
  reshaped freely.
- **building** — at least one unit is `in_progress`, `blocked_on_decision`, `in_verification`,
  or `done`. Reshaping is constrained: you're past the bet.
- **complete** — every unit is `done` AND a learn record exists. The flywheel can pull from it.

State is never stored — it is recomputed on every read. There is no manual transition.

### MCP tool surface (13 tools in `backend/app/mcp_server.py`)
- **Ground yourself:** `get_spec`, `get_conversation_summary`, `get_context`, `list_units`,
  `get_guidance`
- **Build the work:** `claim_unit`, `report_progress`, `submit_for_verification`,
  `get_verification`
- **Escalate:** `raise_decision`, `resolve_decision`, `wait_for_decision`
- **Decompose:** `propose_unit` — you propose; a human confirms (you cannot confirm your own).

Full signatures and the operating loop are in `docs/spec-contract.md`.

### Repo layout
```
doen/
├── CLAUDE.md / agents.md     # this file is the constitution (CLAUDE.md @-imports agents.md)
├── docker-compose.yml        # full stack: pgvector Postgres, Redis, backend, web
├── docs/                     # spec-contract.md, design-principles.md, getting-started.md
├── specs/                    # historical bootstrap (0001, 0007); all new specs live IN Doen
├── .claude/skills/           # repeatable skills (e.g. /sync-docs)
├── backend/app/
│   ├── main.py               # app factory: lifespan, exception handlers, routers
│   ├── config.py / database.py   # settings; shared pool/redis + FastAPI deps
│   ├── models.py             # domain models (the spec contract as Pydantic) + derive_state()
│   ├── schemas.py            # API request/response models — separate from the domain
│   ├── exceptions.py         # domain errors + the HTTP error-mapping handlers
│   ├── store.py              # SpecStore — the only place that touches Postgres / Redis
│   ├── services/             # business logic: shaping, authoring, conversation, learn, decisions
│   ├── providers/            # external integrations: llm, embeddings (pluggable)
│   ├── routers/              # thin APIRouters per domain (specs, units, decisions, projects,
│   │                         #   initiatives, conversation, learn, shaping)
│   ├── mcp_server.py         # the executor-facing MCP tools (stdio)
│   └── migrate.py / backfill_embeddings.py   # ops
└── web/app/…                 # Next.js: project dashboards, living-spec page, conversation rail
```

### Data model — what is a table, what is JSONB
- `initiatives` — one row per initiative. Has `project_id` (required), `seq` (per-project),
  `archived_at` / `archived_reason` (soft delete).
- `specs` — one JSONB document per initiative. Holds intent, constraints, discretion,
  acceptance, references, memory_links.
- `work_units` — separate table. Status: `proposed` → `ready` → `in_progress` →
  `in_verification` → `done` (or `blocked_on_decision`).
- `decisions` — separate table, append-only.
- `messages` — conversation history (initiative-scoped OR project-scoped; exactly one set).
- `projects` — one row per project (id, name, prefix, intent).
- `memory` — embedded snippets the Advisor surfaces across initiatives.

### Active conventions
- **Layered backend.** Request flow: router → service → repository. Routers are thin (no
  try/except — domain exceptions map to HTTP centrally via `register_exception_handlers`).
  Services are framework-agnostic and reusable from the MCP server. The store is the only
  Postgres / Redis caller.
- **Domain vs API shapes are separate.** `models.py` is durable domain; `schemas.py` is wire
  format. Don't conflate them.
- **Providers are pluggable.** LLM + embeddings sit behind tiny interfaces, swappable by env.
- **Soft archive.** Initiatives can be archived (state-aware: "reject" while draft,
  "archive" otherwise). The row stays — `archived_at` + `archived_reason` exclude it from
  active lists.
- **Project-scoped everything.** Each initiative has a `project_id`; the rail, dashboards,
  and `get_context` are project-aware with fallback to global.
- **The Advisor is a single voice.** Both rails (initiative-level and project-level) reach
  one Advisor service that knows the spec, the units, the memory, and the conversation.

## References

- `docs/spec-contract.md` — the schema and MCP interface, in detail. Read when building
  against the contract.
- `docs/design-principles.md` — the rationale, including deliberately rejected directions.
  Read when proposing design changes.
