---
name: sync-docs
description: >
  Audit the three constitution docs (agents.md, docs/spec-contract.md,
  docs/design-principles.md) against the current Doen codebase and the recently
  shipped specs. Identify drift, propose updates, and surface them for human
  confirmation before writing. Use after any spec that touched architecture,
  conventions, or the MCP surface; every ~5 specs as a routine check; or on
  demand when the docs feel out of date.
---

# /sync-docs — keeping the constitution honest

These three docs anchor every session. When they drift from reality, every
session built on top of them inherits the drift — the executor builds against
a constitution that no longer matches the code. This skill is the procedure
for catching that early.

The standing rule (in agents.md) makes doc updates part of the spec that
caused them. This skill is the safety net: it catches drift that slipped
through, or that accumulates from non-spec changes.

## When to run

- **Immediately after a spec ships** that touched architecture, the MCP
  surface, the data model, conventions, or the lifecycle.
- **Every ~5 specs** as a cadence check, even if no single spec felt
  architectural — drift adds up.
- **On demand** when an executor sessions reports that a doc seems wrong,
  or when shaping turns up a contradiction.

## The four-step procedure

### 1. Read the three docs

- `agents.md` — the constitution; structure must be stable-first / volatile-
  last (What Doen is → Stack → Architecture invariants → How we work →
  Keeping these docs current → Current state → References). Must carry a
  `<!-- last-reviewed: YYYY-MM-DD after spec BD-XX -->` header in the first 3
  lines. Must stay under ~200 lines.
- `docs/spec-contract.md` — the TypeScript shapes and the MCP tool surface.
- `docs/design-principles.md` — the rationale and the append-only list of
  rejected directions.

### 2. Compare against current reality

Two sources of truth to reconcile against:

**The codebase** — read these files, in order:
- `backend/app/models.py` — domain model. Check field names, status enums,
  the `State` literal, `derive_state()`, `WorkUnit.status` values, `Spec`
  shape (state vs stage), `Submission`/`Verdict`/`CriterionResult` shapes.
- `backend/app/mcp_server.py` — list every `@mcp.tool()` function, in order.
  Confirm each is documented in `spec-contract.md` under the correct
  grouping (Ground / Escalate / Decompose / Build) with the current
  signature. Watch for tools added since the last review and tools
  renamed or removed.
- `backend/app/routers/` — list HTTP routes per file. Confirm the layered
  router → service → repository discipline is described accurately in
  `agents.md` (Active conventions).
- `backend/migrations/` — newest migration tells you which tables exist
  and what columns were recently added. Cross-check the data-model bullets.
- `web/app/` — the surfaces the rail philosophy describes. Watch for
  drift between principles ("rail stays visible and light", "progressive
  disclosure") and what the components actually do.

**The shipped specs** — list completed initiatives via Doen (`GET
/initiatives`, then filter `state == "complete"`) since the last
`last-reviewed:` header in `agents.md`. For each, read the spec's intent
and acceptance criteria. Specs that touched architecture, conventions, or
the MCP surface MUST have updated at least one of the three docs already —
if not, that spec missed its own standing-rule constraint and is itself
drift.

### 3. Identify drift

Drift comes in three shapes — search for each:

- **Stale concepts.** Doc mentions something the code no longer has. Common
  forms: renamed fields (`stage` vs `state`, `satisfies` vs `criterion_ids`,
  `blocked_by` vs `blocked_on`), removed tools, removed tables, removed
  status values, replaced lifecycles (7-stage → 3-state).
- **Missing additions.** Code has something the doc never picked up.
  Common forms: new MCP tools, new model fields, new tables, new principles
  from a recent spec, new rejected directions.
- **Aspirational fiction.** Doc describes something the code does not do
  yet. Especially in `spec-contract.md` (a phantom tool signature) and
  `design-principles.md` (a principle that hasn't been built). The
  IndexedDB-for-conversations entry resolved during BD-14 is the canonical
  example: an AI-shaped spec mentioned IndexedDB, but the code stored
  conversations in Postgres the whole time.

Also check **the spec that requested this sync**. If you're running the
skill because a recent spec touched architecture, read that spec's
acceptance criteria against the code and the docs. The point of this skill
is to catch drift the spec itself missed.

### 4. Propose updates — for human confirmation, then write

Surface a short audit before editing. For each doc, list the drift you
found and the proposed change. Do not write the doc yet. Format:

```
agents.md
  - [stale]   Line 42 says "X" — code now does Y. Propose: replace "X" with "Y".
  - [missing] New MCP tool `foo()` is not listed. Propose: add to Ground group.
  - [stale]   Architecture invariants count says 6, codebase has 8.

docs/spec-contract.md
  - [stale]   WorkUnit.satisfies — code field is criterion_ids.
  - [missing] Tool get_conversation_summary not documented.

docs/design-principles.md
  - [missing] No rejected direction for {pattern} (rejected in spec BD-NN).
```

Hand that audit to the human. Wait for confirmation — full, partial, or
"don't apply X." Then write each confirmed change. Update the
`<!-- last-reviewed: YYYY-MM-DD after spec BD-XX -->` header in agents.md
to the current date and the most recent spec number.

## Hard rules

- **Do not edit `design-principles.md`'s rejected directions destructively.**
  That section is append-only — existing rejections stay even if the
  surrounding text changes.
- **Do not write before confirming.** A doc is a constitution; an
  unconfirmed edit propagates into every future session.
- **Do not invent a `last-reviewed:` date forward.** Use today and the
  most-recently-shipped spec number.
- **Keep `agents.md` under ~200 lines.** If it's bloating, the new content
  belongs in `spec-contract.md` or `design-principles.md` instead.
- **Pointers in `agents.md`, detail in the other two.** `agents.md` carries
  the high-signal essentials and points outward; it does not duplicate
  schema or rationale.
