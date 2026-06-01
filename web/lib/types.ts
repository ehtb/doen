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
}

// The parent entity listed on the dashboard (backend Initiative, store.py).
export interface Initiative {
  id: string;
  title: string | null;
  state: string; // inferred lifecycle (0011): draft / building / complete
  project_id: string; // the parent project (0010) — every initiative belongs to one
  org_id?: string | null;
  owner_id?: string | null;
  created_at: string;
  updated_at: string;
}

// A group of initiatives under a strategic intent (backend Project, models.py).
export interface Project {
  id: string;
  name: string;
  intent: string;
  created_at: string;
  updated_at: string;
}

// Per-initiative attention indicators (backend InitiativeAttention, models.py) — what the
// project screen surfaces per card so where work is waiting is visible without opening a spec.
export interface InitiativeAttention {
  proposed_items: number;
  open_decisions: number;
  units_to_verify: number;
}

// The project dashboard payload (backend ProjectDashboard, schemas.py).
export interface ProjectDashboard {
  project: Project;
  initiatives: Initiative[];
  open_decisions: number;
  attention: Record<string, InitiativeAttention>;
}

// A work unit decomposed from the spec (backend WorkUnit, store.py). The executor
// proposes and works it over MCP; the human confirms and judges it here.
export interface CriterionResult {
  criterion_id: string;
  result: "pass" | "fail" | "needs_judgment";
  evidence: string;
}

export interface Submission {
  summary: string;
  criteria_results: CriterionResult[];
  artifacts: string[];
  submitted_at: string;
}

export interface Verdict {
  verdict: "approved" | "changes_requested";
  feedback: string;
  decided_by: string;
  decided_at: string;
}

export interface WorkUnit {
  id: string;
  spec_id: string;
  title: string;
  scope: string;
  criterion_ids: string[];
  status: string;
  blocked_on?: string | null;
  progress_note?: string | null;
  submission?: Submission | null;
  verdict?: Verdict | null;
  created_at: string;
  updated_at: string;
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
  units: WorkUnit[];
  memory: Memory[];
}

// A spec item the Advisor proposes on the rail (backend Proposal, schemas.py). Rendered as
// a card; accepting it POSTs to the editing endpoint as an ai_proposed item (0009 a3).
export interface Proposal {
  section: "constraints" | "discretion" | "acceptance";
  text: string;
  verify_kind?: string | null;
  verify_detail?: string | null;
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

// The Advisor's response to a human turn (backend AdvisorTurn, schemas.py).
export interface AdvisorTurn {
  human: Message;
  advisor: Message;
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
