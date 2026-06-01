"use client";

import { useState } from "react";
import useSWR from "swr";
import { GitBranch } from "lucide-react";
import type { Decision } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { DECISIONS_SWR_KEY, decisionsFetcher } from "./AttentionSurface";

// Decisions are fetched via SWR sharing the same key as AttentionSurface, so both components
// stay in sync from a single network request per interval rather than two parallel polls.
export default function SteeringRail({ initiativeId }: { initiativeId: string }) {
  const {
    data: decisions,
    mutate: refreshDecisions,
    error: swrError,
  } = useSWR<Decision[]>(
    DECISIONS_SWR_KEY(initiativeId),
    decisionsFetcher,
    { refreshInterval: 3000, dedupingInterval: 2500, revalidateOnFocus: false },
  );
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [rationales, setRationales] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const error = swrError?.message ?? resolveError;
  const waiting = decisions?.length ?? 0;

  async function resolve(d: Decision, chosen: string) {
    const rationale = (rationales[d.id] ?? "").trim();
    if (!rationale || busy === d.id) return;
    setBusy(d.id);
    setResolveError(null);
    try {
      const res = await fetch(`/api/decisions/${d.id}/resolve`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chosen, rationale }),
      });
      if (!res.ok) throw new Error(`resolve failed (${res.status})`);
      // Optimistic: drop the card immediately, then revalidate from the source of truth.
      await refreshDecisions(
        (cur) => (cur ?? []).filter((x) => x.id !== d.id),
        { revalidate: true },
      );
    } catch (e) {
      setResolveError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <aside id="steering-rail" className="animate-rise [animation-delay:120ms] scroll-mt-6 overflow-hidden rounded-2xl border border-rail-border bg-rail text-rail-foreground shadow-sm">
      <div className="border-b border-rail-border px-5 py-4">
        <div className="flex items-baseline justify-between">
          <span className="font-serif text-[15px] font-semibold">Steering rail</span>
          <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-wide text-rail-muted uppercase">
            <span className="size-[6px] rounded-full bg-confirmed animate-live" />
            live
          </span>
        </div>
        <p className="mt-0.5 font-mono text-[10.5px] tracking-wide text-rail-muted">
          the input surface · {waiting} waiting on you
        </p>
      </div>

      <div className="px-5 py-4">
        {error && <p className="font-mono text-xs text-proposed">{error}</p>}

        {decisions !== undefined && waiting === 0 && !error && (
          <p className="py-2 text-sm text-rail-muted">
            No open decisions — the build is unblocked. When the executor hits a call outside the
            spec, it surfaces here for your judgment.
          </p>
        )}

        <div className="space-y-3.5">
          {(decisions ?? []).map((d) => {
            const rationale = (rationales[d.id] ?? "").trim();
            const enabled = rationale.length > 0 && busy !== d.id;
            return (
              <div
                key={d.id}
                className="animate-glow min-w-0 rounded-xl border border-primary/50 bg-primary/10 p-4"
              >
                <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold tracking-widest text-primary uppercase">
                  <GitBranch className="size-3 shrink-0" /> needs your judgment
                </div>
                <p className="break-words text-sm leading-relaxed text-rail-foreground">{d.question}</p>
                {d.recommendation && (
                  <p className="mt-2.5 break-words text-[12.5px] leading-snug text-rail-muted">
                    <span className="font-mono text-[10px] tracking-wide text-primary uppercase">
                      my rec ·{" "}
                    </span>
                    {d.recommendation}
                  </p>
                )}
                <Textarea
                  rows={2}
                  placeholder="Why this call? (required)"
                  value={rationales[d.id] ?? ""}
                  onChange={(e) => setRationales((r) => ({ ...r, [d.id]: e.target.value }))}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && enabled) {
                      resolve(d, d.options[0]);
                    }
                  }}
                  className="mt-3 max-w-full resize-none border-rail-border bg-rail-card text-rail-foreground placeholder:text-rail-muted"
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  {d.options.map((opt) => (
                    <Button
                      key={opt}
                      size="sm"
                      disabled={!enabled}
                      onClick={() => resolve(d, opt)}
                      title={enabled ? "" : "Add a rationale first"}
                    >
                      {busy === d.id ? "…" : opt}
                    </Button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
