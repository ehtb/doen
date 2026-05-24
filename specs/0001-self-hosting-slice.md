# Spec 0001 — Self-hosting slice

> The first spec. Written in plain files because Doen can't hold a spec yet. The entire point
> of this slice is to change that. Format follows docs/spec-contract.md.

- **initiative:** build-doen
- **stage:** implement
- **version:** 1

## Intent

Reach the point where Doen stores and serves the spec for its own next feature, so that
building Doen _becomes_ dogfooding Doen. Everything here serves that single milestone and
nothing else. This is deliberately the thinnest possible vertical slice — store a spec, serve
it whole, expose it over MCP, render it. No more.

## Constraints — locked, do not cross

- Postgres is the source of truth; Redis is derived and must rebuild from it.
- The spec is one JSONB document, one row per initiative. No per-item tables.
- Decisions are durable rows in their own table.
- Reuse `backend/app/store.py` (the provided models + `SpecStore`) as-is. Don't reinvent it.
- **No auth** in this slice — a single hardcoded dev user is fine. Auth is a later spec.
- **No embeddings / pgvector / memory** — `get_context` may return empty.
- `version` is the optimistic lock; never bypass it.

## Discretion — your call

- Route, module, and file naming; scaffolding choices.
- The dev-user stub mechanism.
- The minimal spec view's appearance — crude and read-only is acceptable.
- `docker-compose` details for local Postgres + Redis.
- Choice of Python MCP server library.

## Acceptance criteria — how this is judged

- **a1** A spec can be created and saved: JSONB in Postgres, mirrored to Redis. `[behavior]`
- **a2** `GET /specs/{initiative_id}` returns the whole spec in one call; warm reads come from
  Redis. `[behavior]`
- **a3** Saving on a stale `version` raises `StaleSpecError` → HTTP 409. `[test]`
- **a4** The MCP server exposes `get_spec`, `raise_decision`, `resolve_decision`, and a way to
  await a resolution. `[behavior]`
- **a5** A minimal web page renders a spec's intent, constraints, discretion, and acceptance
  criteria. `[behavior]`
- **a6 — HEADLINE** Claude Code reads the `build-doen` spec from the _running Doen MCP server_
  (not from `specs/`) and uses it to drive the next feature. `[human_judgment]`

## Work units

- **u1 — scaffold** backend (FastAPI) + web (Next.js) + `docker-compose` (pg + redis); wire
  `SpecStore` into the app lifespan. → setup
- **u2 — persistence + routes** migrations for `initiatives`, `specs`, `decisions`; create /
  save / get spec endpoints. → a1, a2, a3
- **u3 — MCP server** exposing the spec tools over **stdio** (see Decisions). → a4
- **u4 — spec view** minimal Next.js page reading `GET /specs/{id}`. → a5
- **u5 — self-host** seed the `build-doen` initiative + its next-feature spec into the DB;
  point Claude Code's MCP client at Doen. → a6

## Decisions

1. **MCP transport for local dogfooding — stdio vs HTTP/SSE?** — **RESOLVED**
   - Context: stdio handles auth outside the protocol (local subprocess, env credentials);
     Streamable HTTP requires an OAuth 2.1 resource server. The two transports map onto Doen's
     two deployment modes — self-hosted OSS (stdio, no auth) and hosted Pro/Max (HTTP + OAuth).
   - **Chosen: stdio** — for this slice and for the open-source self-hosted path.
   - Rationale: zero auth friction for local dogfooding and OSS onboarding. The hosted
     HTTP + WorkOS path is additive, not a replacement — captured in `specs/0007-hosted-mcp-auth`.
