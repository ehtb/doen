"use client";

import { useCallback, useEffect, useState } from "react";
import { GitBranch } from "lucide-react";
import type { Decision } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// Live-update transport (discretion): short-polling. The rail rarely holds more than a
// handful of open decisions, so a few-second poll needs no SSE/WebSocket infra.
const POLL_MS = 3000;

export default function SteeringRail({ initiativeId }: { initiativeId: string }) {
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rationales, setRationales] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/decisions`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`couldn't load decisions (${res.status})`);
      setDecisions(await res.json());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [initiativeId]);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  async function resolve(d: Decision, chosen: string) {
    const rationale = (rationales[d.id] ?? "").trim();
    if (!rationale || busy) return;
    setBusy(d.id);
    try {
      const res = await fetch(`/api/decisions/${d.id}/resolve`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chosen, rationale }),
      });
      if (!res.ok) throw new Error(`resolve failed (${res.status})`);
      // optimistic: drop the card now, then re-sync from the source of truth
      setDecisions((cur) => (cur ?? []).filter((x) => x.id !== d.id));
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const waiting = decisions?.length ?? 0;

  return (
    <aside className="animate-rise [animation-delay:120ms] sticky top-6 min-w-80 flex-[1_1_360px] self-start overflow-hidden rounded-2xl bg-rail text-rail-foreground shadow-2xl ring-1 ring-black/20">
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

        {decisions !== null && waiting === 0 && !error && (
          <p className="py-2 text-sm text-rail-muted">Nothing waiting — the rail is quiet.</p>
        )}

        <div className="space-y-3.5">
          {(decisions ?? []).map((d) => {
            const rationale = (rationales[d.id] ?? "").trim();
            const enabled = rationale.length > 0 && busy !== d.id;
            return (
              <div
                key={d.id}
                className="animate-glow rounded-xl border border-primary/50 bg-primary/10 p-4"
              >
                <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold tracking-widest text-primary uppercase">
                  <GitBranch className="size-3" /> needs your judgment
                </div>
                <p className="text-sm leading-relaxed text-rail-foreground">{d.question}</p>
                {d.recommendation && (
                  <p className="mt-2.5 text-[12.5px] leading-snug text-rail-muted">
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
                  className="mt-3 border-rail-border bg-rail-card text-rail-foreground placeholder:text-rail-muted"
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
