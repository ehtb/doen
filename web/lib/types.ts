// Mirrors the relevant fields of the backend Spec (backend/app/store.py).

export type InitiativeType = "engineering" | "research";

export interface SpecItem {
  id: string;
  text: string;
  provenance: string;
  status: string;
  created_at: string;
  confirmed_at?: string | null;
  // BD-14: Advisor self-review classification — set after shaping, before human confirmation.
  advisor_classification?: "confident" | "flagged" | "uncertain" | null;
  advisor_classification_reason?: string | null;
}

export interface AcceptanceCriterion extends SpecItem {
  verify: { kind: string; detail: string };
  // BD-5 u2: criteria-as-tracking fields
  verification_status: "pending" | "evidence_submitted" | "verified" | "changes_requested";
  evidence?: string | null;
  verdict?: "approved" | "changes_requested" | null;
  feedback?: string | null;
  // BD-14: Advisor preliminary verification verdict — set after evidence submission.
  advisor_preliminary_verdict?: "pass" | "needs_your_eye" | "borderline" | null;
  advisor_preliminary_notes?: string | null;
}

export interface Spec {
  id: string;
  initiative_id: string;
  version: number;
  state: string; // inferred lifecycle (0011): draft / building / complete
  initiative_type: InitiativeType; // BD-15: engineering or research
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
  // BD-14: Advisor self-review outputs — set after shaping and after evidence submission.
  shaping_review_synthesis?: string | null;
  verification_synthesis?: string | null;
  // Background shaping status: "pending" while the LLM fills the spec async.
  shaping_status?: "pending" | "complete" | "error";
}

// The parent entity listed on the dashboard (backend Initiative, store.py).
export interface Initiative {
  id: string;
  title: string | null;
  state: string; // inferred lifecycle (0011): draft / building / complete
  initiative_type: InitiativeType; // BD-15: engineering or research
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
  drift_reports: number;      // BD-12: pending drift reports attributed to this initiative's memory
  is_shaping?: boolean;       // spec is being drafted in the background
}

// The project dashboard payload (backend ProjectDashboard, schemas.py).
export interface ProjectDashboard {
  project: Project;
  initiatives: Initiative[];
  open_decisions: number;
  pending_drift_reports: number; // BD-12: pending drift reports across all project memory
  attention: Record<string, InitiativeAttention>;
  onboarding_prompt: string; // BD-9: setup prompt from server config for the onboarding hint
}

// LLM-as-judge result stored on a drift report (BD-12).
export interface DriftReportQuality {
  passed: boolean;
  overall: number;        // 0–1 normalised mean score
  scores: { name: string; score: number; reasoning: string }[];
  feedback: string;
  warning: string | null; // improvement suggestion when not passed
}

// A drift report — an agent-filed memory discrepancy awaiting human resolution (BD-12).
export interface DriftReport {
  id: string;
  memory_id: string;
  initiative_id: string | null;
  current_evidence: string;
  is_obsolete: boolean;
  status: "pending" | "approved" | "dismissed" | "initiative_created";
  resolution_note: string | null;
  quality: DriftReportQuality | null; // null if judge was skipped or unavailable
  created_at: string;
  resolved_at: string | null;
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

// BD-17: an actionable heuristic extracted from a completed initiative (backend Heuristic).
export interface Heuristic {
  id: string;
  initiative_id: string;
  project_id?: string | null;
  rule: string;
  tags: string[];
  superseded_by?: string | null;  // initiative_id that superseded this entry
  replaces?: string | null;       // heuristic_id this entry replaces
  created_at: string;
}

// BD-17: one proposed heuristic from the Advisor's draft (backend HeuristicProposal).
export interface HeuristicProposal {
  rule: string;
  tags: string[];
  replaces?: string | null;
}

// BD-17: the Advisor's heuristic draft for human review (backend HeuristicDraftResult).
export interface HeuristicDraftResult {
  initiative_id: string;
  proposals: HeuristicProposal[];
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
  verify?: { kind: string; detail: string } | null;
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
  // BD-13: "human" = human resolved on steering rail; "agent" = Discretion Auditor intercepted.
  resolver_type?: "human" | "agent" | null;
  status: "open" | "resolved";
  created_at: string;
  resolved_at?: string | null;
}

// BD-13: a cause-effect rationale claim cited to a specific decision or criterion record.
export interface RationaleClaim {
  claim: string;
  source_id: string;  // a decision ID (dec_…) or criterion ID (item_…)
  source_type: "decision" | "criterion";
}

// BD-13: the Advisor's draft outcome including structured rationale claims.
export interface OutcomeDraft {
  summary: string;
  learnings: string;
  rationale_claims: RationaleClaim[];
}
