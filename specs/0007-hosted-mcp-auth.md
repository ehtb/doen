# Spec 0007 — Hosted MCP auth (Streamable HTTP + WorkOS)

> **STUB.** Captured now so the transport decision in 0001 has a home for its downstream
> constraints. To be fully shaped — acceptance criteria refined, work units decomposed — when
> the hosted tier is stood up. Format follows docs/spec-contract.md.

- **initiative:** build-doen
- **stage:** shape
- **version:** 0   <!-- draft / unsaved -->
- **depends on:** 0001 (a6, the dogfood milestone); the hosted deployment; the billing/plans spec

## Intent

Give hosted Pro/Max users remote MCP access to their specs — a Streamable HTTP transport
authorized via OAuth 2.1, with WorkOS AuthKit as the authorization server — **without**
compromising the auth-free stdio path that open-source self-hosters rely on. The two
transports coexist: stdio for self-hosted, HTTP + OAuth for hosted.

## Constraints — locked, do not cross

- The HTTP MCP server is an **OAuth 2.1 resource server**: it validates tokens, never issues
  them. The authorization server is WorkOS AuthKit (already integrated, issue #86).
- Token validation uses a **configurable issuer** (JWKS / metadata discovery). WorkOS is wired
  only in the hosted deployment — **never hard-coded in the OSS core.** A self-hoster must be
  able to point at any compliant authorization server, or use stdio and skip auth entirely.
- Tokens must be **audience-bound** and validated as issued *for this server*. Never pass a
  client's token through to upstream services — Doen uses its own credentials for the DB and
  any downstream calls. (No token teleportation.)
- **stdio remains the default** for self-hosted/OSS. HTTP + OAuth is additive, not a
  replacement.
- Client registration (DCR and/or CIMD) is delegated to AuthKit; the resource server only
  publishes protected-resource metadata and verifies bearer tokens.

## Discretion — your call

- FastMCP's `AuthKitProvider` vs a thin custom JWT verifier.
- Scope design for the spec tools (e.g. `spec:read` vs `spec:write`).
- How plan tier (Pro / Max) maps to scopes, rate limits, or quotas.
- Deployment topology — gateway, DNS-rebinding protections, token caching.

## Acceptance criteria — rough, refine when shaped

- A remote MCP client (Claude Code) authenticates via browser OAuth and calls the spec tools
  over Streamable HTTP. `[behavior]`
- A request with no token, or a token not audience-bound to this server, gets `401` plus a
  `WWW-Authenticate` header pointing at the protected-resource metadata. `[test]`
- The OSS stdio path still runs with no auth and no WorkOS dependency present. `[test]`
- Plan tier gates access as intended (Pro vs Max). `[human_judgment]`

## Work units

_Decomposition deferred until the hosted tier is stood up._

## Decisions

_None yet — to be raised during shaping (scope granularity, tier→scope mapping)._
