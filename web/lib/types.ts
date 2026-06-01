// Mirrors the relevant fields of the backend Spec (backend/app/store.py).

export interface SpecItem {
  id: string;
  text: string;
  provenance: string;
  status: string;
  created_at: string;
  confirmed_at?: string | null;
}

export interface AcceptanceCriterion extends SpecItem {
  verify: { kind: string; detail: string };
  // BD-5 u2: criteria-as-tracking fields
  verification_status: "pending" | "evidence_submitted" | "verified" | "changes_requested";
  evidence?: string | null;
  verdict?: "approved" | "changes_requested" | null;
  feedback?: string | null;
}

export interface Spec {
  id: string;
  initiative_id: string;
  version: number;
  state: string; // inferred lifecycle (0011): draft / building / complete
  title: string;
  intent: string;
  constraints: SpecItem[];
  discretion: SpecItem[];
  acceptance: AcceptanceCriterion[];
  references: unknown[];
  memory_links: string[];
  // 0012 u5: the canonical short id (BD-12) + URL slug (bd-12-…), present when the spec is read
  // by ref via /projects/{id}/specs/{ref}. Resolved from the project prefix + per-project seq.
  short_id?: string;
  short_slug?: string;
}

// The parent entity listed on the dashboard (backend Initiative, store.py).
export interface Initiative {
  id: string;
  title: string | null;
  state: string; // inferred lifecycle (0011): draft / building / complete
  project_id: string; // the parent project (0010) — every initiative belongs to one
  seq: number; // immutable per-project sequence (0012 u5) — with the project prefix forms BD-7
  org_id?: string | null;
  owner_id?: string | null;
  created_at: string;
  updated_at: string;
}

// A group of initiatives under a strategic intent (backend Project, models.py).
export interface Project {
  id: string;
  name: string;
  prefix: string; // 0012 u5: the short handle for this project's initiatives (BD -> BD-7)
  intent: string;
  onboarding_dismissed: boolean; // BD-9: server-side dismissal state for the onboarding hint
  archived: boolean; // BD-11: derived from archived_at IS NOT NULL; explicit archive/unarchive only
  created_at: string;
  updated_at: string;
}

// Per-initiative attention indicators (backend InitiativeAttention, models.py) — what the
// project screen surfaces per card so where work is waiting is visible without opening a spec.
export interface InitiativeAttention {
  proposed_items: number;
  open_decisions: number;
  criteria_to_verify: number; // BD-7: acceptance criteria with evidence submitted awaiting verdict
}

// The project dashboard payload (backend ProjectDashboard, schemas.py).
export interface ProjectDashboard {
  project: Project;
  initiatives: Initiative[];
  open_decisions: number;
  attention: Record<string, InitiativeAttention>;
  onboarding_prompt: string; // BD-9: setup prompt from server config for the onboarding hint
}

// An append-only record the Learn stage writes (backend Memory, store.py).
export interface Memory {
  id: string;
  initiative_id: string;
  summary: string;
  learnings?: string | null;
  outcome?: Record<string, unknown> | null;
  created_at: string;
}

// The Learn-stage review: outcome vs. intent (backend LearnReview, routes.py).
export interface LearnReview {
  initiative: Initiative;
  intent: string;
  decisions: Decision[];
  memory: Memory[];
}

// A spec item the Advisor proposes on the rail (backend Proposal, schemas.py). Rendered as
// a card; accepting it POSTs to the editing endpoint as an ai_proposed item (0009 a3).
export interface Proposal {
  section: "constraints" | "discretion" | "acceptance";
  text: string;
  verify_kind?: string | null;
  verify_detail?: string | null;
  verdict?: "accepted" | "dismissed";
}

// One turn on the conversation rail (backend Message, models.py). The Advisor's proposal
// cards ride along in metadata.proposals.
export interface Message {
  id: string;
  initiative_id?: string | null; // set for an initiative-rail message
  project_id?: string | null; // set for a project-rail message (0010 u5); exactly one owner
  role: "human" | "advisor";
  content: string;
  metadata: { proposals?: Proposal[] } & Record<string, unknown>;
  created_at: string;
}

// The Advisor's response to a rail turn (backend AdvisorReply, schemas.py). Just the Advisor's
// message — the human's turn already lives in the browser (IndexedDB). The frontend writes this
// reply into IndexedDB itself; nothing is persisted server-side (spec uvama).
//
// BD-1 u3: on a PROJECT turn the Advisor may synthesise the discussion into a *proposed* initiative
// description — it rides here, deliberately NOT in message.metadata, so the rail can surface a
// 'Create initiative from this' action without ever persisting the synthesis. Null otherwise.
export interface AdvisorReply {
  message: Message;
  proposed_initiative?: string | null;
}

// An escalation on the steering rail. Mirrors backend Decision (store.py).
export interface Decision {
  id: string;
  question: string;
  options: string[];
  recommendation?: string | null;
  chosen?: string | null;
  rationale?: string | null;
  raised_by: string;
  decided_by?: string | null;
  status: "open" | "resolved";
  created_at: string;
  resolved_at?: string | null;
}
