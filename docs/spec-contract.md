# Doen — The Spec Contract

The seam between the intent layer (where humans author and steer) and the executors (Claude Code, CI agents, anything that builds). One artifact, two faces: a **schema** Doen stores, and an **MCP interface** agents consume and reply through.

---

## Governing principle

Everything below exists to enforce one rule for any agent working an initiative:

> **Act within the constraints. Decide freely within the discretion. Escalate everything else that is a product or intent call.**

Constraints and discretion together partition the decision space the human has already reasoned about. Anything outside both — that isn't a pure implementation detail — is not the agent's to resolve silently. It becomes a decision raised back to the human.

A second rule makes the artifact binding:

> **The spec is the only source of truth. Nothing in chat, a ticket, or a side instruction governs an agent until it has been confirmed into the spec.**

Conversation is how things *get into* the spec. The spec is what *governs*. This is what makes "react to the agent's understanding" safe: a misread costs nothing until it's confirmed.

---

## The spec object

Expressed as TypeScript interfaces for readability; maps directly to Pydantic on the FastAPI side.

```typescript
type Provenance = "human" | "ai_proposed" | "ai_confirmed_by_human";
type ItemStatus = "proposed" | "confirmed" | "retired";

interface SpecItem {
  id: string;
  text: string;
  provenance: Provenance;       // who originated it — drives the rail's visual trust cues
  status: ItemStatus;           // proposed items do NOT govern agents; only confirmed ones do
  created_at: string;
  confirmed_at?: string;
}

interface AcceptanceCriterion extends SpecItem {
  verify: {
    kind: "test" | "behavior" | "metric" | "human_judgment";
    detail: string;             // test path, behaviour description, metric+threshold, or rubric
  };
}

interface Reference {                       // the "pointing" input — dense intent
  id: string;
  kind: "code" | "prior_initiative" | "design" | "doc" | "external";
  pointer: string;              // repo path, initiative id, url
  note: string;                 // the human's framing of why it's relevant
}

interface Decision {                        // append-only judgment log
  id: string;
  question: string;
  options: string[];
  recommendation?: string;      // the agent's suggested option when it raised this
  chosen?: string;              // filled on resolution
  rationale?: string;           // the human's reasoning — feeds memory later
  raised_by: "agent" | "human";
  decided_by?: string;
  status: "open" | "resolved";
  emitted_item_ids?: string[];  // constraints/criteria this decision wrote into the spec
  created_at: string;
  resolved_at?: string;
}

interface Spec {
  id: string;
  initiative_id: string;
  version: number;              // bumps on every confirmed change — it is a living document
  stage: "discover" | "shape" | "bet" | "decompose" | "implement" | "verify" | "learn";
  title: string;

  intent: string;               // the narrative human voice: the why and the what
  constraints: SpecItem[];      // must / must-not — agents do not cross these
  discretion: SpecItem[];       // explicit latitude — agents decide freely here
  acceptance: AcceptanceCriterion[];
  references: Reference[];
  decisions: Decision[];
  memory_links: string[];       // prior initiatives surfaced during shaping
}

interface WorkUnit {                        // the decomposition — the demoted "board"
  id: string;
  spec_id: string;
  title: string;
  scope: string;
  satisfies: string[];          // acceptance criterion ids this unit contributes to
  status: "ready" | "in_progress" | "blocked_on_decision" | "in_verification" | "done";
  blocked_by?: string;          // decision id, when blocked
}
```

Note what is **absent on purpose**: no story points, no effort estimate, no velocity, anywhere. Appetite, if you keep it, lives on the bet at the initiative level — never as per-unit precision that would only be confidently wrong.

---

## The MCP contract (executor-facing)

This is the Implement ↔ Verify loop. The authoring side (the agent that helps *draft* the spec during shaping) is a separate, smaller toolset operating on the same objects; keeping the two surfaces distinct stops the executor from quietly rewriting intent.

```typescript
// --- ground yourself ---
get_spec(initiative_id): Spec
// Read before acting. Returns the full living spec at its current version.

get_context(initiative_id, query): { snippets: ContextSnippet[] }
// Semantic retrieval over the codebase's intent and prior initiatives (pgvector).
// Use to learn WHY things are as they are before changing them — prevents "fixing"
// what was deliberate.

list_units(spec_id, status?): WorkUnit[]
// Your assigned work.

// --- when you hit a call that isn't yours to make ---
raise_decision(initiative_id, question, context, options, recommendation?): Decision
// For anything outside constraints + discretion that is a product/intent call.
// Appears in the human's steering rail. Returns a Decision in status "open".
// Do not guess. Continue other units or yield while it's open.

get_decision(decision_id): Decision
// Poll for resolution. When resolved, returns the chosen option and rationale; the spec
// may have gained a constraint or criterion — re-fetch get_spec if `version` changed.

// --- progress and handoff ---
report_progress(unit_id, note, percent?): { ok: boolean }
// Lightweight heartbeat; keeps the agent strip on the rail honest.

submit_for_verification(unit_id, summary, criteria_results, artifacts): { queued: boolean }
// Hand a unit back for human judgment. You map your own output to each criterion;
// the human verifies intent-alignment, not your diff line-by-line.
//   criteria_results: { criterion_id, result: "pass" | "fail" | "needs_judgment", evidence }[]
//   artifacts:        { kind: "diff" | "preview" | "test_run" | "note", pointer }[]

get_verification(unit_id): { verdict: "approved" | "changes_requested" | "pending", feedback?: string }
// On "changes_requested", feedback returns and the unit reopens at "in_progress".

interface ContextSnippet { source: string; kind: Reference["kind"]; text: string; relevance: number; }
```

---

## The operating loop

1. `get_spec` — ground in intent, constraints, discretion, criteria, references.
2. `list_units` — take a unit that is `ready`.
3. Build. Use `get_context` to understand prior intent before touching anything established.
4. At every non-trivial choice, classify it: covered by a constraint → obey; within granted discretion → decide and move on; otherwise, if it's a product/intent call → `raise_decision` and either pick up another unit or yield. Never resolve it silently.
5. `get_decision` to retrieve the human's call; re-`get_spec` if the version bumped (a decision may have added a constraint or criterion).
6. When the unit satisfies its criteria, self-check each one, then `submit_for_verification` with per-criterion results and evidence.
7. `get_verification` — `approved` closes the unit; `changes_requested` reopens it with feedback. The human judged outcome-against-intent, not syntax.

On `learn`, Doen embeds the resolved decisions and the outcome-vs-intent delta back into memory, where `get_context` and `memory_links` will surface them for the next initiative. That is the flywheel — and it compounds faster in an agentic world, because more gets built per unit of human time, so more is learned.

---

## Storage mapping (FastAPI + Postgres + pgvector)

| Table | Holds | pgvector |
|---|---|---|
| `specs` | id, initiative_id, version, stage, title, intent | `intent_embedding` — powers memory similarity & `memory_links` |
| `spec_items` | type (`constraint`/`discretion`/`acceptance`), text, provenance, status, verify_* | `scope_embedding` on constraints — powers live drift detection against incoming work |
| `references` | kind, pointer, note | — |
| `decisions` | append-only judgment log | `decision_embedding` — retrieved by `get_context` and at shaping time |
| `work_units` | scope, satisfies[], status, blocked_by | — |
| `memory` | completed-initiative summaries + outcomes | embedding for cross-initiative retrieval |

Drift detection falls out for free: embed each confirmed constraint, then as units add scope, score the new scope against the constraint embeddings. A divergence above threshold is a drift signal on the rail — the same mechanism, reused.

---

## What is deliberately NOT in the contract

These omissions are the product. Each one keeps a decision human:

- **No self-approval.** `submit_for_verification` only ever *queues*. A verdict can only come from a human via `get_verification`. An agent cannot mark its own work accepted.
- **No prioritisation.** Agents take assigned units; they never sequence bets or decide what's worth doing. That's the human Bet stage.
- **No silent product decisions.** Anything outside constraints + discretion that bears on intent *must* go through `raise_decision`. Resolving it in code is the one unforgivable move.
- **No estimation.** No points, no hours, no velocity — anywhere. Fake precision, especially under accelerated engineering, is worse than honest uncertainty.
- **No authority without the spec.** An agent acts only on confirmed spec items. Chat, tickets, and asides have no force until a human has confirmed them in. The spec is the contract.
