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
