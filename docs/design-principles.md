# Doen — Design Principles & Rationale

> The *why* behind the decisions. Read this when making a design or architecture call, or when
> tempted to add something. It is reference material — not auto-loaded every session, so it
> doesn't cost context until it's needed. The hard rules live in CLAUDE.md and the specs; this
> explains the thinking and records the paths we deliberately rejected.

## Product thesis

Doen is the **intent layer** that sits *above* agentic executors (Claude Code, CI agents).
Humans author and steer a living spec; executors build against it and surface decisions back.
Doen is where you decide what's worth building and verify it was built right — not where code
is written by hand.

The unifying pattern across everything: **a precise source-of-truth artifact generates and
continuously reconciles everything downstream.** A shaped initiative becomes a spec; the spec
drives the build; work and decisions flow back into the spec. The spec is the protagonist.

## The human / AI boundary

The role of the human is moving up the stack to intent-definition and verification, with little
hand-coding. The bottleneck is no longer writing code — it's *specifying intent precisely* and
*verifying the result*. Design for that.

Governing rule for any agent: **act within constraints, decide freely within discretion,
escalate everything else that is a product or intent call.** Constraints and discretion
partition the decision space the human has already reasoned about; anything outside both, if it
bears on intent, is an escalation — never a silent choice in code.

What AI is good at here: shaping (drafting, surfacing missing pieces, asking the right
questions), slicing a first draft, drift detection, narrative/status generation, and
remembering across initiatives. What stays human, always: deciding what's worth doing
(bets/prioritisation), setting appetite, judging quality and outcome, and authoring the spec's
intent. These are not gaps to close later — they are the product.

## Interface principles

- **Correction over authoring.** The highest-fidelity, lowest-effort input is a human reacting
  to the agent's articulated understanding, not filling a blank form. Build for "no, not that —
  this." The agent's legibility is the real input mechanism.
- **Dialogue in, spec out.** Conversation is the input medium; the spec is the durable artifact.
  Don't conflate them. A transcript is the worst thing to hand an agent.
- **The spec is the only source of truth.** Nothing in chat, a ticket, or an aside governs an
  agent until it's confirmed into the spec. This is what makes reacting-to-understanding safe:
  a misread costs nothing until confirmed.
- **Input is continuous, not up-front.** A low-latency channel for mid-flight decisions, but
  notification-driven — pulling the human in only for genuine judgment, never draining attention.
- **Two surfaces.** A warm, document-like spec (the artifact) and a distinct conversation rail
  (the input). Keeping them visually separate is the point.

## Architecture stance

- **Postgres is the only source of truth. Redis is derived** and always rebuildable from it.
  Nothing durable lives only in Redis (ephemeral heartbeats/locks excepted).
- **The spec is a document aggregate** — one JSONB row per initiative. Almost every read is
  "load the whole spec by id," so don't normalise it into join-heavy tables.
- **`version` is an optimistic lock.** The spec is living; humans and agents both touch it.
- **Decisions are durable rows** (append-only, individually addressable, embeddable for memory),
  not nested JSON.
- **No estimation anywhere** — no points, hours, or velocity. Fake precision under accelerated
  engineering is worse than honest uncertainty.
- **MCP server is a resource server, not an issuer** — it validates audience-bound tokens and
  never passes them through to upstream services.

## Business model & deployment

Open-source core, plus a hosted tier with paid plans (Pro, Max). The two MCP transports map
onto the two modes:

- **Self-hosted / OSS → stdio.** No network boundary, no auth, zero onboarding friction.
- **Hosted → Streamable HTTP + OAuth 2.1**, with WorkOS AuthKit as the authorization server.

Keep the commercial auth vendor at the edge: the OSS core validates tokens from a *configurable*
issuer, so self-hosters are never forced onto WorkOS. (Captured in specs/0007.)

## The interface prototype

`docs/prototypes/living-spec.jsx` is the **north-star design** for the eventual conversation-rail
UI — the two-surface model, provenance cues, the constraint/discretion boundary, the escalation
card. It is a reference, **not production code**, and explicitly **out of scope for 0001** (whose
UI is intentionally crude and read-only). Realise it later, in its own UI spec.

## Deliberately rejected — do not re-propose

- **Consultancy / delivery-intelligence framing.** Abandoned because it's a distribution trap:
  consultants are usually forced into the client's PM tool, so the buyer can't adopt it. The
  initiative-lifecycle framing replaced it.
- **Rebuilding the executor.** Doen does not try to be where code gets written — that's Claude
  Code's layer, and it's commoditising. Doen is the intent + memory + verification layer above,
  which is the defensible, unowned ground.
- **Redis as the sole durable store.** Tempting for speed, but it trades away the durable,
  queryable history that is the moat. Redis is the hot path; Postgres is the truth.
