---
name: sync-docs
description: >
  Audit the project's core documentation (constitution) against the current
  codebase and recently completed work. Identify drift, propose updates,
  and surface them for human confirmation before writing. Use after any 
  significant change that touched architecture, conventions, or public 
  interfaces; every ~5 tasks as a routine check; or on demand when docs 
  feel out of date.
---

# /sync-docs — keeping the constitution honest

A project's core documentation files (the constitution) anchor every session. 
When they drift from reality, every session built on top of them inherits 
the drift — the executor builds against a constitution that no longer 
matches the code. This skill is the procedure for catching that early.

Documentation updates should ideally happen alongside the changes that 
caused them. This skill is the safety net: it catches drift that slipped 
through, or that accumulates from non-obvious changes.

## When to run

- **Immediately after significant changes** that touch architecture, 
  public interfaces (APIs/tools), the data model, or core conventions.
- **Regularly** (e.g., every ~5 tasks) as a cadence check, even if no 
  single change felt architectural — drift adds up.
- **On demand** when an executor session reports that a doc seems 
  wrong, or when a contradiction is found during planning.

## The four-step procedure

### 1. Identify and read core documentation

Locate the files that define the project's identity and technical 
standards. These typically include:

- **Core Context / Constitution:** (e.g., `agents.md`, `CLAUDE.md`, 
  `GEMINI.md`, `README.md`) — Defines what the project is, the stack, 
  architecture invariants, and how the team works.
- **Technical Contract / API Spec:** (e.g., `docs/spec-contract.md`, 
  `openapi.yaml`, `schema.graphql`) — Defines the data shapes and 
  interface surface.
- **Design Principles / Rationale:** (e.g., `docs/design-principles.md`, 
  `ARCHITECTURE.md`) — Records the "why" behind decisions and the 
  append-only list of rejected directions.

### 2. Compare against current reality

Reconcile the documentation against the truth in the codebase and 
recent history:

**The codebase** — Identify and read primary source-of-truth files:
- **Domain Models:** Look for the core domain model or entity definitions 
  (e.g., `models.py`, `types.ts`, `entities.go`). Check field names, 
  status enums, and state transitions.
- **Interface Surface:** Look for public interface definitions 
  (e.g., API routes, MCP tools, controllers). Confirm each is documented 
  accurately in the technical contract.
- **Data Evolution:** Check recent database migrations or schema 
  definitions to see how the data model has evolved.
- **Visuals / Components:** For UI-heavy projects, check if components 
  still align with documented design principles (e.g., "progressive 
  disclosure", "minimalist layout").

**Recent history:**
- Review recently completed tasks, PRs, or initiatives since the last 
  documented review date.
- For each, check if changes to architecture, conventions, or interfaces 
  were reflected in the docs. If a change missed its own documentation 
  requirement, it is considered drift.

### 3. Identify drift

Drift typically manifests in three shapes:

- **Stale concepts:** Docs mention something the code no longer has. 
  Common forms: renamed fields, removed tools, removed tables, removed 
  status values, or replaced lifecycles.
- **Missing additions:** Code has something the docs never picked up. 
  Common forms: new interfaces, new model fields, new tables, or new 
  principles established during recent tasks.
- **Aspirational fiction:** Docs describe something the code does not do 
  yet. This often happens when a plan mentions a feature that was later 
  deferred or implemented differently.

### 4. Propose updates — for human confirmation, then write

Surface a short audit before editing. For each doc, list the drift 
found and the proposed change. Do not write the doc yet. Format:

```
{file_path}
  - [stale]   Line {N} says "X" — code now does Y. Propose: replace "X" with "Y".
  - [missing] New interface `foo()` is not listed. Propose: add to {Section}.
  - [stale]   Architecture invariant {A} is no longer true because of {B}.
```

Hand this audit to the human. Wait for confirmation — full, partial, 
or "don't apply X." Then write each confirmed change. Update any 
`last-reviewed:` headers (or equivalent) in the core docs to the 
current date and most recent task identifier.

## Hard rules

- **Do not write before confirming.** A doc is a constitution; an 
  unconfirmed edit propagates into every future session.
- **Preserve append-only sections.** Sections like "Rejected Directions" 
  stay even if surrounding text changes.
- **Respect size constraints.** If a core doc has a stated line limit 
  (e.g., ~200 lines), maintain it. Move details to secondary docs.
- **Maintain pointers.** Keep core docs high-signal and point outward 
  to detail files rather than duplicating content.
