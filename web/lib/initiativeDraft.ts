// Hand-off channel for the project rail's "Create initiative from this" action (BD-1 u3).
//
// The rail never creates anything — that deliberate act belongs to the creation form. When the
// human clicks the action, the rail stashes the Advisor's synthesised description here and signals
// the form to pre-fill it. The synthesis is transient: it is NOT a message and never lands in the
// conversation store; it lives only until the form consumes it.
//
// Two carriers, on purpose: sessionStorage survives a route transition / reload (the form reads it
// on mount), and a window event covers the common same-page case where the form is already mounted
// alongside the rail. The draft is consumed once — read-then-clear — so it can't re-fill later.
//
// BD-20: the draft now carries an optional `initiative_type` so a discovery conversation that
// identified research vs. engineering framing can pre-select the type in the creation form.

import type { InitiativeType } from "./types";

export const PREFILL_EVENT = "doen:prefill-initiative";

export interface InitiativeDraft {
  description: string;
  initiative_type?: InitiativeType;
  // BD-22: when set, the initiative was created from this observation — resolve it after creation.
  observation_id?: string;
}

const keyFor = (projectId: string) => `doen:initiative-draft:${projectId}`;

/** Stash a synthesised description (and optional type/observation) for `projectId`'s creation form and signal it to pre-fill. */
export function stashInitiativeDraft(
  projectId: string,
  description: string,
  initiative_type?: InitiativeType,
  observation_id?: string,
): void {
  const draft: InitiativeDraft = {
    description,
    ...(initiative_type ? { initiative_type } : {}),
    ...(observation_id ? { observation_id } : {}),
  };
  try {
    sessionStorage.setItem(keyFor(projectId), JSON.stringify(draft));
  } catch {
    // sessionStorage can be unavailable (private mode, quota) — the event still drives the
    // same-page case, and the payload travels in the event detail as a fallback below.
  }
  window.dispatchEvent(
    new CustomEvent(PREFILL_EVENT, {
      detail: {
        projectId,
        description,
        ...(initiative_type ? { initiative_type } : {}),
        ...(observation_id ? { observation_id } : {}),
      },
    }),
  );
}

/** Read and clear the stashed draft for `projectId` (one-shot). Null when there's nothing pending. */
export function consumeInitiativeDraft(projectId: string): InitiativeDraft | null {
  try {
    const v = sessionStorage.getItem(keyFor(projectId));
    if (v !== null) {
      sessionStorage.removeItem(keyFor(projectId));
      try {
        return JSON.parse(v) as InitiativeDraft;
      } catch {
        // Old format (plain string from before BD-20) — treat as description-only.
        return { description: v };
      }
    }
    return null;
  } catch {
    return null;
  }
}
