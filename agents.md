<!-- last-reviewed: 2026-06-09 sync-docs audit -->
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
- **Store:** Postgres = source of truth for the durable record (specs, decisions,
  memory, projects). Redis = derived hot cache + real-time coordination (decision pub/sub).
  Conversation history is NOT here — it's browser-local (IndexedDB) since spec uvama; the backend
  is stateless about messages (see Current state).
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
   into per-item tables. Decisions are a separate table; spec items are not.
3. **Decisions are durable rows** in their own table, not nested in the spec doc.
4. **Every initiative belongs to a project.** `project_id` is required — there are no orphan
   specs.
5. **`version` is an optimistic lock.** Never bypass the stale-version check on write.
6. **No estimation anywhere** — no story points, no hours, no velocity. Ever.
7. **State is primarily derived.** Initiative lifecycle (draft / building / learning / complete)
   is inferred from criteria verification status + the learn record via `_recompute_state()`.
   Two explicit escape-hatch transitions exist for human control: `start-building`
   (draft → building) and `revert-to-draft` (building → draft). All other state movement is
   automatic; executors never set state directly.
8. **You never self-approve work.** Verification is queued for the human; only they issue a
   verdict.

## How we work

- **Why these rules, and what we've rejected:** consult `docs/design-principles.md` before
  proposing design or architecture changes — it records the rationale and the paths we
  deliberately chose not to take.
- **Spec-driven.** Build only what the active spec covers. Out-of-scope ideas become a note,
  not code. Specs live IN Doen — fetch via `get_spec` from the running MCP server.
- **Ground in the why, not just the what.** Pair `get_spec` with `get_conversation_summary`
  — the former tells you what to build, the latter tells you the resolved decisions, rejected
  alternatives, and stated priorities behind it. Don't re-decide what's settled.
- **Specialized Agents.** Use the specialized agents in `.claude/agents/` to maintain quality and consistency:
  - **`implementer`**: Invoke for all feature work, module scaffolding, and spec translation. It enforces the layered architecture and async patterns.
  - **`reviewer`**: Invoke after implementation but before handoff. It validates against the spec and project invariants.
- **Governing principle:** act within the constraints, decide freely within the discretion,
  **escalate everything else that is a product or intent call.** Do not guess on intent.
- **Surfacing a decision:** when you hit a call outside constraints + discretion, call
  `raise_decision`. Then STOP. Resolving an intent question in code is the one unforgivable
  move.
- **Self-verify before handing off.** Check each acceptance criterion explicitly and submit
  evidence via `submit_evidence`. The human judges intent-alignment, not your diff line-by-line.
- **Small commits.** One logical change per commit.

## Keeping these docs current

> Any spec that changes architecture, conventions, or the MCP surface must update agents.md, spec-contract.md, and/or design-principles.md as part of its acceptance criteria.

That sentence is binding — doc updates ride along with the spec that caused them, never
deferred to a follow-up. Review cadence: every ~5 specs, or immediately after any spec that
touches architecture, conventions, or the MCP surface. Run the `/sync-docs` skill
(`.claude/skills/sync-docs/SKILL.md`) on demand to audit drift between these three docs and
the codebase — and to surface proposed updates back to a human for confirmation.

## Current state — volatile; expect drift fastest here

### Lifecycle (initiative state)
Four states inferred from criteria verification status + the learn record by
`SpecStore._recompute_state()` in `backend/app/store.py`, then stored on the initiative row
and spec JSONB:
- **draft** — no acceptance criteria, or no criterion has had evidence submitted yet. The spec
  can still be reshaped freely.
- **building** — at least one criterion has evidence submitted (`verification_status` is
  `evidence_submitted`, `verified`, or `changes_requested`).
- **learning** — every criterion is `verified` but no learn record exists yet. The spec is
  frozen; the human writes the retrospective to close it.
- **complete** — every criterion is `verified` AND a learn record exists. The flywheel can
  pull from it.

State is stored on the initiative row and recomputed by `_recompute_state()` whenever criteria
or the learn record change. Two human-facing escape hatches exist (`start-building`,
`revert-to-draft`) but executors do not call them.

### MCP tool surface (11 tools in `backend/app/mcp_server.py`)
- **Ground yourself:** `get_spec`, `get_conversation_summary`, `get_context`
  - `get_context` hits include `type: "heuristic"` (BD-17) in addition to `"decision"` and `"memory"`. Heuristic hits carry `heuristic_id` (cite when classifying `confident`) and `superseded_by` (non-null means this rule is obsolete — do not use for `confident` classification).
- **Track criteria:** `submit_evidence`, `get_criteria_status`
- **Escalate:** `raise_decision`, `resolve_decision`, `wait_for_decision`
- **Project setup:** `setup_project`
- **Memory verification (BD-12):** `report_memory_drift`, `list_memory_for_audit`
  - After every `get_context` memory hit, run a Consistency Check against the codebase; call
    `report_memory_drift(memory_id, current_evidence, is_obsolete)` when you find a mismatch.
  - `list_memory_for_audit(project_id, staleness_window_days=30)` returns only entries not
    verified within the window — use it to drive a batch audit pass.

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
│   ├── models.py             # domain models (the spec contract as Pydantic)
│   ├── schemas.py            # API request/response models — separate from the domain
│   ├── exceptions.py         # domain errors + the HTTP error-mapping handlers
│   ├── store.py              # SpecStore — the only place that touches Postgres / Redis
│   ├── services/             # business logic: advisor, authoring, conversation, decisions, discretion_auditor, evaluation, learn, review, shaping
│   ├── providers/            # external integrations: llm, embeddings (pluggable)
│   ├── routers/              # thin APIRouters per domain (specs, decisions, projects,
│   │                         #   initiatives, conversation, learn, shaping, drift_reports)
│   ├── mcp_server.py         # the executor-facing MCP tools (stdio)
│   └── migrate.py / backfill_embeddings.py   # ops
└── web/app/…                 # Next.js: project dashboards, living-spec page, conversation rail
```

### Data model — what is a table, what is JSONB
- `initiatives` — one row per initiative. Has `project_id` (required), `seq` (per-project),
  `initiative_type` ("engineering" or "research", set at creation, immutable — BD-15),
  `archived_at` / `archived_reason` (soft delete).
- `specs` — one JSONB document per initiative. Holds intent, constraints, discretion,
  acceptance, references, memory_links.
- acceptance criteria — tracked as fields inside the `specs` JSONB document. Each criterion
  carries `verification_status` (`pending` → `evidence_submitted` → `verified`), `evidence`,
  `verdict`, and `feedback` directly on the criterion object. No separate table.
- `decisions` — separate table, append-only.
- conversation history — NOT a table (dropped in spec uvama). It lives in the browser's
  IndexedDB, keyed per initiative/project; the backend never reads or writes it. Each Advisor
  call carries a windowed slice in its request body, which the backend uses for the prompt and
  discards.
- `projects` — one row per project (id, name, prefix, intent).
- `memory` — embedded snippets the Advisor surfaces across initiatives.
- `heuristics` — append-only actionable rules extracted from completed initiatives (BD-17). Distinct from memory summaries; supersession records an evolution chain without erasure.
- `observations` — advisor-generated observations for a project (BD-22). Each can be resolved into an initiative; `resolved_initiative_id` is set on resolution.

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
  one Advisor service that knows the spec, the memory, and the conversation.

## References

- `docs/spec-contract.md` — the schema and MCP interface, in detail. Read when building
  against the contract.
- `docs/design-principles.md` — the rationale, including deliberately rejected directions.
  Read when proposing design changes.
