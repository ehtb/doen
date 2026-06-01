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
  stage: string;
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
  stage: string;
  org_id?: string | null;
  owner_id?: string | null;
  created_at: string;
  updated_at: string;
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
