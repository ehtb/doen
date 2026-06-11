"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import { GitBranch } from "lucide-react";
import type { Decision, InitiativeType } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { DECISIONS_SWR_KEY, decisionsFetcher } from "./AttentionSurface";

// Decisions are fetched via SWR sharing the same key as AttentionSurface, so both components
// stay in sync from a single network request per interval rather than two parallel polls.
export default function SteeringRail({
  initiativeId,
  initiativeType = "engineering",
}: {
  initiativeId: string;
  initiativeType?: InitiativeType;
}) {
  const {
    data: decisions,
    mutate: refreshDecisions,
    error: swrError,
  } = useSWR<Decision[]>(
    DECISIONS_SWR_KEY(initiativeId),
    decisionsFetcher,
    { refreshInterval: 3000, dedupingInterval: 2500, revalidateOnFocus: false },
  );
  const [open, setOpen] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [rationales, setRationales] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  // Auto-open when decisions arrive
  useEffect(() => {
    if (decisions !== undefined && decisions.length > 0) setOpen(true);
  }, [decisions?.length]);

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
    <aside id="steering-rail" className="animate-rise [animation-delay:120ms] scroll-mt-6 overflow-hidden rounded-xl border border-border bg-card shadow-none">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-[14px] py-[10px] text-left transition-colors hover:bg-card/80"
      >
        <div className="flex items-center gap-1.5">
          <span className="text-[12px]">⚡</span>
          <span className="text-[13px] font-medium text-foreground">Steering rail</span>
          <span className={cn("text-[11px]", waiting > 0 ? "text-confirmed-foreground" : "text-ink-faint")}>
            · {waiting > 0 ? `${waiting} waiting on you` : "0 waiting on you"}
          </span>
        </div>
        <span
          className="text-[9px] text-ink-faint transition-transform duration-150"
          style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)", display: "inline-block" }}
        >
          ▸
        </span>
      </button>

      {open && (
        <div className="border-t border-border px-[14px] pb-3 pt-[10px]">
          {error && <p className="font-mono text-xs text-proposed">{error}</p>}

          {decisions !== undefined && waiting === 0 && !error && (
            <div className="rounded-md px-3 py-2.5 mb-2" style={{ background: "#EDF2E9" }}>
              <p className="text-[12.5px] text-confirmed-foreground">
                {initiativeType === "research"
                  ? "No open questions — the investigation is unblocked."
                  : "No open decisions — the build is unblocked."}
              </p>
            </div>
          )}

          <div className="space-y-2.5">
            {(decisions ?? []).map((d) => {
              const rationale = (rationales[d.id] ?? "").trim();
              const enabled = rationale.length > 0 && busy !== d.id;
              return (
                <div
                  key={d.id}
                  className="min-w-0 rounded-lg border border-primary/40 p-3.5"
                  style={{ background: "#FAF6F0" }}
                >
                  <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold tracking-widest text-primary uppercase">
                    <GitBranch className="size-3 shrink-0" /> needs your judgment
                  </div>
                  <p className="break-words text-[13px] leading-relaxed text-foreground">{d.question}</p>
                  {d.recommendation && (
                    <p className="mt-2 break-words text-[12px] leading-snug text-ink-soft">
                      <span className="font-mono text-[9.5px] tracking-wide text-primary uppercase">rec · </span>
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
                    className="mt-3 max-w-full resize-none border-border bg-card text-foreground placeholder:text-ink-faint"
                  />
                  <div className="mt-2.5 flex flex-wrap gap-2">
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
      )}
    </aside>
  );
}
