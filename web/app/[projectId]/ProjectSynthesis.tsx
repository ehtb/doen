"use client";

// BD-22: Unified advisor synthesis surface — persistent observations (each resolvable into
// an initiative) + 'what we know' cross-initiative synthesis. Replaces BD-20's plain-text
// observations blob with individually-actionable, persisted records.

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp, GitBranch, Sparkles, X } from "lucide-react";
import type { Observation, ProjectSynthesisResponse, WhatWeKnow } from "@/lib/types";
import { stashInitiativeDraft } from "@/lib/initiativeDraft";
import { cn } from "@/lib/utils";

export const SYNTHESIS_CACHE_PREFIX = "doen:synthesis:v2";

export function sessionCacheKey(projectId: string, completedCount: number): string {
  return `${SYNTHESIS_CACHE_PREFIX}:${projectId}:${completedCount}`;
}

export default function ProjectSynthesis({
  projectId,
  completedCount,
}: {
  projectId: string;
  completedCount: number;
}) {
  const [observations, setObservations] = useState<Observation[]>([]);
  const [whatWeKnow, setWhatWeKnow] = useState<WhatWeKnow | null>(null);
  const [loading, setLoading] = useState(completedCount > 0);
  const [whatWeKnowOpen, setWhatWeKnowOpen] = useState(false);
  const [resolvedOpen, setResolvedOpen] = useState(false);

  useEffect(() => {
    if (completedCount === 0) return;

    const key = sessionCacheKey(projectId, completedCount);
    try {
      const cached = sessionStorage.getItem(key);
      if (cached) {
        const data = JSON.parse(cached) as ProjectSynthesisResponse;
        setObservations(data.observations ?? []);
        setWhatWeKnow(data.what_we_know);
        setLoading(false);
        return;
      }
    } catch {}

    fetch(`/api/projects/${projectId}/synthesis`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((json: ProjectSynthesisResponse | null) => {
        if (json) {
          setObservations(json.observations ?? []);
          setWhatWeKnow(json.what_we_know);
          try {
            sessionStorage.setItem(key, JSON.stringify(json));
          } catch {}
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId, completedCount]);

  if (completedCount === 0) return null;

  if (loading) {
    return (
      <div className="mb-5 rounded-lg border border-border bg-card/40 px-4 py-3 animate-pulse">
        <div className="flex items-center gap-2 font-mono text-[11px] text-ink-faint">
          <Sparkles className="size-3 text-primary/50" />
          Advisor is reviewing project history…
        </div>
      </div>
    );
  }

  const open = observations.filter((o) => o.status === "open");
  const resolved = observations.filter((o) => o.status === "resolved" || o.status === "rejected");

  if (open.length === 0 && resolved.length === 0 && !whatWeKnow) return null;

  return (
    <div className="mb-5 space-y-2">
      {open.map((obs) => (
        <ObservationCard
          key={obs.id}
          observation={obs}
          projectId={projectId}
          onOptimisticResolve={(id) =>
            setObservations((prev) =>
              prev.map((o) => (o.id === id ? { ...o, status: "resolved" } : o)),
            )
          }
          onOptimisticReject={(id) =>
            setObservations((prev) =>
              prev.map((o) => (o.id === id ? { ...o, status: "rejected" } : o)),
            )
          }
        />
      ))}

      {resolved.length > 0 && (
        <div className="rounded-lg border border-border bg-card/20 px-4 py-2">
          <button
            type="button"
            onClick={() => setResolvedOpen((v) => !v)}
            className="flex w-full items-center justify-between font-mono text-[10px] text-ink-faint tracking-[0.1em] uppercase"
          >
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="size-3" />
              {resolved.length} past observation{resolved.length === 1 ? "" : "s"}
            </span>
            {resolvedOpen ? (
              <ChevronUp className="size-3" />
            ) : (
              <ChevronDown className="size-3" />
            )}
          </button>
          {resolvedOpen && (
            <div className="mt-2 space-y-3 pt-2 border-t border-border">
              {resolved.map((obs) => (
                <ResolvedObservation key={obs.id} observation={obs} />
              ))}
            </div>
          )}
        </div>
      )}

      {whatWeKnow && (
        <div className="rounded-lg border border-border bg-card/40 px-4 py-2.5">
          <button
            type="button"
            onClick={() => setWhatWeKnowOpen((o) => !o)}
            className="flex w-full items-center justify-between font-mono text-[10px] font-semibold tracking-[0.11em] text-ink-soft uppercase"
          >
            <span className="flex items-center gap-1.5">
              <Sparkles className="size-3 text-primary/60" />
              What we know
            </span>
            {whatWeKnowOpen ? (
              <ChevronUp className="size-3" />
            ) : (
              <ChevronDown className="size-3" />
            )}
          </button>
          {whatWeKnowOpen && (
            <div className="mt-2.5 space-y-3">
              <WhatWeKnowSection label="Patterns" content={whatWeKnow.patterns} />
              <WhatWeKnowSection label="Assumptions" content={whatWeKnow.assumptions} />
              <WhatWeKnowSection label="Intent alignment" content={whatWeKnow.intent_alignment} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ObservationCard({
  observation,
  projectId,
  onOptimisticResolve,
  onOptimisticReject,
}: {
  observation: Observation;
  projectId: string;
  onOptimisticResolve: (id: string) => void;
  onOptimisticReject: (id: string) => void;
}) {
  const [confirmingReject, setConfirmingReject] = useState(false);

  const handleResolve = useCallback(() => {
    onOptimisticResolve(observation.id);
    stashInitiativeDraft(projectId, observation.content, undefined, observation.id);
    const formEl = document.getElementById(`new-initiative-${projectId}`);
    if (formEl) {
      formEl.scrollIntoView({ behavior: "smooth", block: "center" });
      formEl.focus();
    }
  }, [observation, projectId, onOptimisticResolve]);

  const handleRejectConfirm = useCallback(async () => {
    onOptimisticReject(observation.id);
    try {
      await fetch(`/api/observations/${observation.id}/reject`, { method: "POST", cache: "no-store" });
    } catch {}
  }, [observation.id, onOptimisticReject]);

  return (
    <div className="rounded-lg border border-border bg-card/40 px-4 py-3.5">
      <div className="flex items-center gap-1.5 mb-2 font-mono text-[10.5px] font-semibold tracking-[0.13em] text-accent-deep uppercase">
        <Sparkles className="size-3" />
        Advisor observation
      </div>
      <p className="text-sm leading-relaxed text-foreground/80">{observation.content}</p>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={handleResolve}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/8",
            "px-2.5 py-1 font-mono text-[10.5px] text-accent-deep tracking-wide",
            "transition-colors hover:bg-primary/15 hover:border-primary/50",
          )}
        >
          <GitBranch className="size-3" />
          Resolve into an initiative
        </button>
        {confirmingReject ? (
          <span className="inline-flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleRejectConfirm}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/8",
                "px-2.5 py-1 font-mono text-[10.5px] text-destructive/80 tracking-wide",
                "transition-colors hover:bg-destructive/15",
              )}
            >
              Confirm dismiss
            </button>
            <button
              type="button"
              onClick={() => setConfirmingReject(false)}
              className="font-mono text-[10px] text-ink-faint hover:text-ink-soft"
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmingReject(true)}
            className={cn(
              "inline-flex items-center gap-1 rounded-md border border-border",
              "px-2.5 py-1 font-mono text-[10.5px] text-ink-faint tracking-wide",
              "transition-colors hover:text-ink-soft hover:border-border/80",
            )}
          >
            <X className="size-3" />
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}

function ResolvedObservation({ observation }: { observation: Observation }) {
  const isRejected = observation.status === "rejected";
  return (
    <div className="space-y-0.5">
      <p className="text-[12.5px] leading-relaxed text-foreground/40 line-through decoration-foreground/20">
        {observation.content}
      </p>
      {isRejected ? (
        <p className="font-mono text-[10px] text-ink-faint">dismissed</p>
      ) : (
        observation.resolved_initiative_id && (
          <p className="font-mono text-[10px] text-ink-faint">
            → resolved as{" "}
            <span className="text-ink-soft">{observation.resolved_initiative_id}</span>
          </p>
        )
      )}
    </div>
  );
}

function WhatWeKnowSection({
  label,
  content,
}: {
  label: string;
  content: string;
}) {
  return (
    <div>
      <div className="mb-1 font-mono text-[9.5px] tracking-[0.1em] text-ink-faint uppercase">
        {label}
      </div>
      <p className="text-[13px] leading-relaxed text-foreground/80">{content}</p>
    </div>
  );
}
