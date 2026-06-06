"use client";

// BD-20: proactive advisor observations and 'what we know' synthesis, shown on the project page.
// Fetched client-side (LLM call — should not block page render) and cached in sessionStorage
// keyed by projectId + completedCount so it auto-updates when a new initiative completes.

import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Sparkles, X } from "lucide-react";
import type { ProjectSynthesisResponse, WhatWeKnow } from "@/lib/types";

function sessionCacheKey(projectId: string, completedCount: number): string {
  return `doen:synthesis:${projectId}:${completedCount}`;
}

export default function ProjectSynthesis({
  projectId,
  completedCount,
}: {
  projectId: string;
  completedCount: number;
}) {
  const [data, setData] = useState<ProjectSynthesisResponse | null>(null);
  const [loading, setLoading] = useState(completedCount > 0);
  const [dismissed, setDismissed] = useState(false);
  const [whatWeKnowOpen, setWhatWeKnowOpen] = useState(false);

  useEffect(() => {
    if (completedCount === 0) return;

    const key = sessionCacheKey(projectId, completedCount);
    try {
      const cached = sessionStorage.getItem(key);
      if (cached) {
        setData(JSON.parse(cached));
        setLoading(false);
        return;
      }
    } catch {}

    fetch(`/api/projects/${projectId}/synthesis`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((json: ProjectSynthesisResponse | null) => {
        if (json) {
          setData(json);
          try {
            sessionStorage.setItem(key, JSON.stringify(json));
          } catch {}
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId, completedCount]);

  if (completedCount === 0 || dismissed) return null;

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

  if (!data?.advisor_observations && !data?.what_we_know) return null;

  return (
    <div className="mb-5 rounded-lg border border-border bg-card/40 px-4 py-3.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 font-mono text-[10.5px] font-semibold tracking-[0.13em] text-accent-deep uppercase">
          <Sparkles className="size-3" />
          Advisor's observations
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="text-ink-faint transition-colors hover:text-ink-soft"
          title="Dismiss"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {data.advisor_observations && (
        <p className="mt-2.5 text-sm leading-relaxed text-foreground/80">
          {data.advisor_observations}
        </p>
      )}

      {data.what_we_know && (
        <div className="mt-3 border-t border-border pt-3">
          <button
            type="button"
            onClick={() => setWhatWeKnowOpen((o) => !o)}
            className="flex w-full items-center justify-between font-mono text-[10px] font-semibold tracking-[0.11em] text-ink-soft uppercase"
          >
            <span>What we know</span>
            {whatWeKnowOpen ? (
              <ChevronUp className="size-3" />
            ) : (
              <ChevronDown className="size-3" />
            )}
          </button>

          {whatWeKnowOpen && (
            <div className="mt-2.5 space-y-3">
              <WhatWeKnowSection
                label="Patterns"
                content={data.what_we_know.patterns}
              />
              <WhatWeKnowSection
                label="Assumptions"
                content={data.what_we_know.assumptions}
              />
              <WhatWeKnowSection
                label="Intent alignment"
                content={data.what_we_know.intent_alignment}
              />
            </div>
          )}
        </div>
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
