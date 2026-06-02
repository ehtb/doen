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
type State      = "draft" | "building" | "learning" | "complete"; // derived from criteria; stored in DB

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
  // BD-5 criteria-as-tracking fields — set by submit_evidence and human verdict actions:
  verification_status: "pending" | "evidence_submitted" | "verified" | "changes_requested";
  evidence?:  string;           // the executor's submitted evidence text
  verdict?:   "approved" | "changes_requested";  // human's verdict on the evidence
  feedback?:  string;           // human's feedback when requesting changes
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
  state: State;                 // derived from criteria verification status + learn record (see SpecStore._recompute_state)
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
  resolver_type?: "human" | "agent"; // BD-13: human = steering rail; agent = auditor
  status: "open" | "resolved";
  emitted_item_ids?: string[];  // constraints / criteria this decision wrote into the spec
  created_at: string;
  resolved_at?: string;
}
```

Work units are the decomposition — also a separate table:

```typescript
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
  onboarding_dismissed: boolean; // BD-9: server-side dismissal of onboarding
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

This is the Implement ↔ Verify loop. Eleven tools, in `backend/app/mcp_server.py`. The authoring side (which helps *draft* the spec during shaping) is exposed via the HTTP API, not the MCP — keeping the two surfaces distinct stops the executor from quietly rewriting intent.

### Ground yourself

```typescript
get_spec(initiative_id): Spec & {
  initiative: { id, title, state },
  advisor_summary: null,   // always null since spec uvama (conversations are browser-local)
  unit_context: {},        // always empty — work units were dropped in BD-5
}
// Read before acting. The current version, the lifecycle state, and all acceptance criteria
// including their current verification_status, evidence, verdict, and feedback.

get_conversation_summary(initiative_id): {
  key_decisions: { question, chosen, rationale }[],
  rejected_alternatives: { question, alternatives }[],
  stated_priorities: string[],  // always [] since spec uvama (conversations are browser-local)
}
// Read WHY this spec is the way it is. Pairs with get_spec — the spec tells you what to build,
// this tells you what was already decided (resolved decisions + their rejected alternatives).

get_context(initiative_id, query): {
  initiative_id: string, project_id: string | null, query: string,
  hits: ContextHit[],
}
// Semantic retrieval (pgvector) over the codebase's intent and prior initiatives. Project-
// scoped with fallback to global. Use to learn WHY established things are as they are
// before changing them — prevents "fixing" what was deliberate.
```

### Escalate (when a call isn't yours to make)

```typescript
raise_decision(
  initiative_id, question, options,
  recommendation?,
): Decision
// For anything outside constraints + discretion that bears on intent. Appears on the
// human's steering rail. Returns the open Decision.

resolve_decision(decision_id, chosen, rationale, decided_by): Decision
// Record the human's verdict. Wakes anyone awaiting via wait_for_decision.

wait_for_decision(decision_id, timeout?): Decision
// Block until resolved. Redis pub/sub — no poll loop. Throws on timeout.
```

### Track and hand off

```typescript
submit_evidence(
  initiative_id,
  criteria_results: { criterion_id, result: "pass" | "fail" | "needs_judgment", evidence }[],
): { version: number, updated_criteria: string[] }
// Submit evidence for one or more acceptance criteria. Sets verification_status →
// evidence_submitted on each criterion and bumps the spec version. All-or-nothing: unknown
// criterion_ids reject the whole call with no state change. The human issues a verdict via
// the dashboard — you cannot approve your own evidence.

get_criteria_status(initiative_id): {
  initiative_id: string,
  criteria: { id, verification_status, evidence?, verdict?, feedback? }[],
}
// Current verification state for all acceptance criteria. Use after submit_evidence to see
// the human's verdict, or to ground yourself before building.

### Setup & Verification (BD-9, BD-12)

```typescript
setup_project(project_path): { status: "ok", project_path, files_written: string[] }
// Install Doen onboarding documents (CLAUDE.md, agents.md) into the target directory.

report_memory_drift(memory_id, current_evidence, is_obsolete, initiative_id?): {
  status: "ok", report_id, quality: { passed, overall, feedback, warning }
}
// Report a discrepancy between a memory hit and the current codebase. Memory is NOT
// updated until a human approves. Includes LLM-as-judge quality feedback.

list_memory_for_audit(project_id, staleness_window_days?): {
  project_id, entries: { memory_id, initiative_id, summary, last_verified_at }[]
}
// Drive a batch audit: retrieve stale memory entries to verify against the codebase.
```

interface ContextHit {
  initiative_id: string;
  type: "decision" | "memory";
  text: string;
  score: number;
  scope: "project" | "global" | null;
  has_pending_drift: boolean; // BD-12: Warns if the memory is already being audited
}
```

---

## The operating loop

1. `get_spec` and `get_conversation_summary` — ground in intent, constraints, discretion, criteria, _and the reasoning behind them_.
2. `get_context` — retrieve prior patterns before touching anything established; prevents re-deciding what was deliberate.
3. Build against the confirmed acceptance criteria. At every non-trivial choice, classify it: covered by a constraint → obey; within granted discretion → decide and move on; otherwise, if it's a product/intent call → `raise_decision`. Never resolve it silently. `wait_for_decision` to resume.
4. When your work satisfies a criterion, call `submit_evidence` with `{ criterion_id, result, evidence }` for each criterion addressed. The spec version bumps and the human sees the evidence on the rail.
5. `get_criteria_status` — once the human has reviewed, check verdicts. `verified` means accepted; `changes_requested` means the criterion reopens with feedback. Address feedback and re-submit evidence.
6. Repeat until every criterion is `verified`. The backend transitions the initiative to `learning` automatically; the human writes the retrospective to advance to `complete`.

On `complete` (every criterion verified + learn record written), Doen embeds the resolved decisions and the outcome-vs-intent delta back into memory, where `get_context` and `memory_links` will surface them for the next initiative. That is the flywheel — and it compounds faster in an agentic world, because more gets built per unit of human time, so more is learned.

---

## Storage mapping (FastAPI + Postgres + pgvector)

| Table | Holds | pgvector |
|---|---|---|
| `initiatives` | one row per initiative: id, project_id, seq, title, state, archived_at, archived_reason | — |
| `specs` | one JSONB document per initiative: intent, constraints[], discretion[], acceptance[] (each criterion carries verification_status/evidence/verdict/feedback), references[], memory_links[] | `intent_embedding` — powers memory similarity & `memory_links` |
| `decisions` | append-only judgment log | `decision_embedding` — retrieved by `get_context` |
| _(conversation history)_ | NOT a Postgres table — browser-local in IndexedDB since spec uvama; the backend is stateless about messages | — |
| `projects` | id, name, prefix, intent | — |
| `memory` | completed-initiative summaries + outcomes | embedding for cross-initiative retrieval |

Spec items (constraints, discretion, acceptance) live inside the `specs` JSONB document — they are *not* a separate table. The spec is read whole. Drift detection runs by embedding confirmed constraints and scoring new scope against them; the same mechanism is reused for the Advisor's contextual briefings.

---

## What is deliberately NOT in the contract

These omissions are the product. Each one keeps a decision human:

- **No self-approval.** `submit_evidence` only ever *submits*. A verdict can only come from a human — an agent cannot mark its own evidence accepted. The human issues criterion verdicts via the dashboard.
- **No prioritisation.** Agents take assigned units; they never sequence bets or decide what's worth doing. That's the human Bet stage.
- **No silent product decisions.** Anything outside constraints + discretion that bears on intent *must* go through `raise_decision`. Resolving it in code is the one unforgivable move.
- **No estimation.** No points, no hours, no velocity — anywhere. Fake precision, especially under accelerated engineering, is worse than honest uncertainty.
- **No manual lifecycle advance.** State is derived from criteria verification status + learn record by the backend. There is no "start building" or "mark complete" tool.
- **No authority without the spec.** An agent acts only on confirmed spec items. Chat, tickets, and asides have no force until a human has confirmed them in. The spec is the contract.
