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

## Lifecycle is inferred, not authored

Initiatives have three states — **draft**, **building**, **complete** — and the state is
*derived* from work units + the learn record on every read, never stored. A spec is `draft`
until a unit moves past `ready`; `building` while any unit is in motion; `complete` when every
unit is `done` AND the human has written a learn record. The reason: the human's job is
intent, not status-keeping. A status field invites status games (drag from "todo" to "in
progress" to feel productive); a derived state can't be gamed because it just reads the work.
This also makes "what stage are we at?" deterministic — there is no race between the lifecycle
column and reality.

## The Advisor — one voice, two rails

A single Advisor service (`backend/app/services/conversation.py`) is the conversation partner
on both the initiative rail and the project rail. It knows the spec, the units in flight, the
memory across past initiatives, and the conversation it's a turn within. It is *not* a chat
assistant — it is the voice that walks the human through shaping, guided review, kickoff,
verification, and learning. Two rails, one voice, so the human builds one mental model of who
they're talking to.

## Progressive disclosure and guided review

The spec page is long because the spec is the whole intent. To stop it being overwhelming:
sections are collapsible, the **review** is conversation-led on the rail (the Advisor walks
each proposed item past the human, building the document live as they go), and the page's
attention follows the work — the rail goes quiet when there are no decisions, the kickoff
surface appears when the spec is fully reviewed but no units exist yet, and after build the
page steers to the learn step. The principle: every moment has a single clear next action,
and the surfaces that aren't relevant recede.

## Project as first-class container

Every initiative belongs to a project — there are no orphan specs. A project carries an
`intent` of its own (the standing context all its initiatives inherit), an attention view
(open decisions, in-flight units, drafts you abandoned mid-shape), and project-scoped memory.
`get_context` is project-aware: it retrieves from the project's prior initiatives first and
falls back to the global memory. This is what makes Doen useful for a real org — multiple
streams of work, each with their own accumulated learning, without bleed between them.

## Description-first creation

Initiatives start from a paragraph — the human's framing in their own voice — not a blank
spec form. The Advisor reads the description and proposes a first-cut spec (intent,
constraints, discretion, acceptance) which the human then reviews and corrects. This pushes
the human's effort into the place they're best at (saying what they want and reacting to a
draft) and away from places they're worst at (filling structured forms cold).

## The conversation rail stays visible and light

The rail is always present but always recessive — never dark, never auto-collapsing,
never competing with the document for attention. It complements; it doesn't shout. When
there are no open decisions, the rail says so plainly: "the build is unblocked." When the
Advisor has something to surface, the surfacing is calm, not modal.

## The interface prototype

`docs/prototypes/living-spec.jsx` is the **north-star design** for the eventual conversation-rail
UI — the two-surface model, provenance cues, the constraint/discretion boundary, the escalation
card. It is a reference, **not production code**, and explicitly **out of scope for 0001** (whose
UI is intentionally crude and read-only). Realise it later, in its own UI spec.

## Deliberately rejected — do not re-propose

> Append-only. Existing entries do not get removed.

- **Consultancy / delivery-intelligence framing.** Abandoned because it's a distribution trap:
  consultants are usually forced into the client's PM tool, so the buyer can't adopt it. The
  initiative-lifecycle framing replaced it.
- **Rebuilding the executor.** Doen does not try to be where code gets written — that's Claude
  Code's layer, and it's commoditising. Doen is the intent + memory + verification layer above,
  which is the defensible, unowned ground.
- **Redis as the sole durable store.** Tempting for speed, but it trades away the durable,
  queryable history that is the moat. Redis is the hot path; Postgres is the truth.
- **A 7-stage manual lifecycle** (discover → shape → bet → decompose → implement → verify →
  learn). Replaced in spec 0011 by the 3-state inferred model (draft / building / complete).
  The 7-stage model put the human in the role of status-keeper and invited drift between the
  field and reality. The inferred model can't lie because it just reads the units.
- **Conversation storage in the browser only.** Considered (IndexedDB / localStorage) for
  privacy and zero-server-state — rejected because it sacrifices the cross-device, cross-
  session continuity the Advisor needs and the durable transcript that feeds memory. The
  `messages` table in Postgres is the truth; resolved during spec BD-14 (Docs That Stay True).
- **Auto-collapsing or dark conversation rail.** Tried briefly; it makes the rail feel modal
  and competitive with the document. The rail stays visible and light — recessive, not absent.
- **A separate "status" column or "stage" enum on the initiative.** Implied by the
  inferred-state principle above, but worth its own line: no field, no setter, no migration
  scaffolds it back in. State is computed from work units + learn record, full stop.
- **Spec items as their own table.** Tempting for "queryable constraints," but the spec is
  read whole on every load and the JSONB document keeps the optimistic-lock + version model
  trivially correct. Work units and decisions live in their own tables; spec items do not.
- **Self-confirming work units.** An executor proposing a unit and then immediately claiming
  it would collapse the human's role at decomposition. Confirmation is the human's signal
  that the decomposition matches their head; preserve it.
