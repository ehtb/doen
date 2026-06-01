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

Expressed as TypeScript interfaces for readability; maps directly to Pydantic models in `backend/app/models.py`.

```typescript
type Provenance = "human" | "ai_proposed" | "ai_confirmed_by_human";
type ItemStatus = "proposed" | "confirmed" | "retired";
type State      = "draft" | "building" | "complete";   // derived, never stored

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

interface Reference {
  id: string;
  kind: "code" | "prior_initiative" | "design" | "doc" | "external";
  pointer: string;              // repo path, initiative id, url
  note: string;                 // the human's framing of why it's relevant
}

interface Spec {
  id: string;
  initiative_id: string;
  version: number;              // optimistic lock; bumps on every confirmed change
  state: State;                 // derived from work units + learn record (see derive_state)
  title: string;

  intent: string;               // the narrative human voice: the why and the what
  constraints: SpecItem[];      // must / must-not — agents do not cross these
  discretion: SpecItem[];       // explicit latitude — agents decide freely here
  acceptance: AcceptanceCriterion[];
  references: Reference[];
  memory_links: string[];       // prior initiatives surfaced during shaping
}
```

Decisions are not embedded in the spec; they are durable rows in their own table:

```typescript
interface Decision {
  id: string;
  question: string;
  options: string[];
  recommendation?: string;      // the executor's suggested option when it raised this
  chosen?: string;              // filled on resolution
  rationale?: string;           // the human's reasoning — feeds memory later
  raised_by: "agent" | "human";
  decided_by?: string;
  status: "open" | "resolved";
  emitted_item_ids?: string[];  // constraints / criteria this decision wrote into the spec
  created_at: string;
  resolved_at?: string;
}
```

Work units are the decomposition — also a separate table:

```typescript
type UnitStatus =
  | "proposed"                  // executor proposed it; a human must confirm
  | "ready"                     // confirmed and claimable
  | "in_progress"               // claimed by an executor
  | "blocked_on_decision"       // parked on an open decision
  | "in_verification"           // submitted; awaiting human verdict
  | "done";                     // human-approved

interface CriterionResult {
  criterion_id: string;
  result: "pass" | "fail" | "needs_judgment";
  evidence: string;
}

interface Submission {
  summary: string;
  criteria_results: CriterionResult[];
  artifacts: string[];          // free-form pointers (paths, urls, notes)
  submitted_at: string;
}

interface Verdict {
  verdict: "approved" | "changes_requested";
  feedback?: string;
  decided_by: string;
  decided_at: string;
}

interface WorkUnit {
  id: string;
  spec_id: string;
  title: string;
  scope: string;
  criterion_ids: string[];      // acceptance criteria this unit contributes to
  status: UnitStatus;
  blocked_on?: string;          // decision_id, when blocked
  progress_note?: string;       // last heartbeat from report_progress
  submission?: Submission;      // present after submit_for_verification
  verdict?: Verdict;            // present after the human's verdict
  created_at: string;
  updated_at: string;
}
```

Surrounding objects an executor will also encounter:

```typescript
interface Initiative {
  id: string;                   // short, per-project slug
  project_id: string;           // required — no orphan specs
  seq: number;                  // per-project sequence number
  title: string;
  state: State;                 // mirrors the spec's derived state
  archived_at?: string;
  archived_reason?: string;
  created_at: string;
  updated_at: string;
}

interface Project {
  id: string;
  name: string;
  prefix: string;               // short handle derived from name (drives short IDs)
  intent: string;
  created_at: string;
  updated_at: string;
}

interface Message {              // conversation history — browser-local (IndexedDB), NOT Postgres
  id: string;                    //   (spec uvama). The backend never stores it; each Advisor call
  initiative_id?: string;        //   carries a windowed slice in its body and discards it.
  project_id?: string;           // exactly one of initiative_id or project_id is set
  role: "human" | "advisor";
  content: string;
  metadata: object;              // structured payloads (e.g. the Advisor's proposal cards)
  created_at: string;
}
```

Note what is **absent on purpose**: no story points, no effort estimate, no velocity, anywhere. Appetite, if you keep it, lives on the bet at the initiative level — never as per-unit precision that would only be confidently wrong.

---

## The MCP contract (executor-facing)

This is the Implement ↔ Verify loop. Thirteen tools, in `backend/app/mcp_server.py`. The authoring side (which helps *draft* the spec during shaping) is exposed via the HTTP API, not the MCP — keeping the two surfaces distinct stops the executor from quietly rewriting intent.

### Ground yourself

```typescript
get_spec(initiative_id): Spec & {
  initiative: { id, title, state },
  advisor_summary: null,                          // always null since spec uvama (see note)
  unit_context?: { [unit_id]: {                   // durable per-unit context:
    submission_summary?, verdict?, verification_feedback?
  }}
}
// Read before acting. The current version, the lifecycle state, and the durable reasoning
// around each unit (submissions + the human's verdict/feedback). NOTE: advisor_summary and the
// per-unit advisor_review were message-derived; conversations are browser-local now (spec uvama),
// so advisor_summary is always null and advisor_review is gone — get_spec narrows to what is
// durable in Postgres.

get_conversation_summary(initiative_id): {
  key_decisions: { question, chosen, rationale }[],
  rejected_alternatives: { question, alternatives }[],
  stated_priorities: string[],                    // always [] since spec uvama (see note)
}
// Read WHY this spec is the way it is. Pairs with get_spec — the spec tells you what to build,
// this tells you what was already decided (resolved decisions + their rejected alternatives).
// NOTE: stated_priorities came from the human's message turns; conversations are browser-local
// now (spec uvama), so the backend can't read them — it degrades to an empty list.

get_context(initiative_id, query): { snippets: ContextSnippet[] }
// Semantic retrieval (pgvector) over the codebase's intent and prior initiatives. Project-
// scoped with fallback to global. Use to learn WHY established things are as they are
// before changing them — prevents "fixing" what was deliberate.

list_units(spec_id, status?): WorkUnit[]
// Your assigned work. Filter by status to find what's ready or blocked.

get_guidance(unit_id): {
  spec_excerpt: string, criteria: AcceptanceCriterion[],
  memory: ContextSnippet[], pitfalls: string[],
}
// The Advisor's contextual briefing for a unit — what to look out for before you start.
```

### Escalate (when a call isn't yours to make)

```typescript
raise_decision(
  initiative_id, question, options,
  recommendation?, unit_id?,
): Decision
// For anything outside constraints + discretion that bears on intent. Appears on the
// human's steering rail. Returns the open Decision. Pass unit_id to park that unit on
// it (blocked_on_decision) — resolving the decision auto-resumes the unit.

resolve_decision(decision_id, chosen, rationale, decided_by): Decision
// Record the human's verdict. Wakes anyone awaiting via wait_for_decision.

wait_for_decision(decision_id, timeout?): Decision
// Block until resolved. Redis pub/sub — no poll loop. Throws on timeout.
```

### Decompose

```typescript
propose_unit(spec_id, title, scope, criterion_ids): WorkUnit
// Propose a unit naming the acceptance criteria it satisfies. Created `proposed`.
// You cannot confirm your own unit — a human does that via the dashboard.
```

### Build and hand off

```typescript
claim_unit(unit_id): WorkUnit
// ready → in_progress. Only a unit a human has confirmed can be claimed.

report_progress(unit_id, note, percent?): { ok: boolean }
// Lightweight heartbeat; updates progress_note on the unit.

submit_for_verification(unit_id, summary, criteria_results, artifacts): { queued: boolean }
// in_progress → in_verification. Map your own output to each criterion; the human verifies
// intent-alignment, not your diff line-by-line. (The Advisor's auto-posted preliminary review
// was retired in spec uvama — it was delivered only as a rail message, and the backend no
// longer writes the browser-local conversation.)
//   criteria_results: { criterion_id, result: "pass" | "fail" | "needs_judgment", evidence }[]
//   artifacts:        string[]   // free-form pointers (paths, urls, notes)

get_verification(unit_id):
  { verdict: "approved" | "changes_requested" | "pending", feedback?: string }
// On `approved`, the unit is done. On `changes_requested`, the unit reopens at in_progress
// with the human's feedback returned. Judged outcome-against-intent, not syntax.

interface ContextSnippet { source: string; kind: Reference["kind"]; text: string; relevance: number; }
```

---

## The operating loop

1. `get_spec` and `get_conversation_summary` — ground in intent, constraints, discretion, criteria, _and the reasoning behind them_.
2. `list_units` — find a unit that is `ready`. `get_guidance` on it for the Advisor's brief.
3. `claim_unit`, then build. Use `get_context` to understand prior intent before touching anything established.
4. At every non-trivial choice, classify it: covered by a constraint → obey; within granted discretion → decide and move on; otherwise, if it's a product/intent call → `raise_decision` (optionally with `unit_id` to park the unit). Never resolve it silently. `wait_for_decision` to resume.
5. `report_progress` as you go — keeps the human's view of your work honest.
6. When the unit satisfies its criteria, self-check each one, then `submit_for_verification` with per-criterion results and evidence.
7. `get_verification` — `approved` closes the unit; `changes_requested` reopens it with feedback. Stop after submission; do not claim the next unit until the human has issued the verdict.

On `complete` (every unit done + learn record written), Doen embeds the resolved decisions and the outcome-vs-intent delta back into memory, where `get_context` and `memory_links` will surface them for the next initiative. That is the flywheel — and it compounds faster in an agentic world, because more gets built per unit of human time, so more is learned.

---

## Storage mapping (FastAPI + Postgres + pgvector)

| Table | Holds | pgvector |
|---|---|---|
| `initiatives` | one row per initiative: id, project_id, seq, title, archived_at, archived_reason | — |
| `specs` | one JSONB document per initiative: intent, constraints[], discretion[], acceptance[], references[], memory_links[] | `intent_embedding` — powers memory similarity & `memory_links` |
| `work_units` | scope, criterion_ids[], status, blocked_on, progress_note, submission, verdict | — |
| `decisions` | append-only judgment log | `decision_embedding` — retrieved by `get_context` |
| _(conversation history)_ | NOT a Postgres table — browser-local in IndexedDB since spec uvama; the backend is stateless about messages | — |
| `projects` | id, name, prefix, intent | — |
| `memory` | completed-initiative summaries + outcomes | embedding for cross-initiative retrieval |

Spec items (constraints, discretion, acceptance) live inside the `specs` JSONB document — they are *not* a separate table. The spec is read whole. Drift detection runs by embedding confirmed constraints and scoring new scope against them; the same mechanism is reused for the Advisor's contextual briefings.

---

## What is deliberately NOT in the contract

These omissions are the product. Each one keeps a decision human:

- **No self-approval.** `submit_for_verification` only ever *queues*. A verdict can only come from a human via `get_verification`. An agent cannot mark its own work accepted. Similarly, you cannot confirm a unit you proposed.
- **No prioritisation.** Agents take assigned units; they never sequence bets or decide what's worth doing. That's the human Bet stage.
- **No silent product decisions.** Anything outside constraints + discretion that bears on intent *must* go through `raise_decision`. Resolving it in code is the one unforgivable move.
- **No estimation.** No points, no hours, no velocity — anywhere. Fake precision, especially under accelerated engineering, is worse than honest uncertainty.
- **No manual lifecycle advance.** State is derived from work units + learn record. There is no "start building" or "mark complete" tool.
- **No authority without the spec.** An agent acts only on confirmed spec items. Chat, tickets, and asides have no force until a human has confirmed them in. The spec is the contract.
