"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Hammer, Link2, ListChecks, RotateCcw } from "lucide-react";
import type { AcceptanceCriterion, WorkUnit } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

// Units change out-of-band: the executor proposes, reports progress, and submits over
// MCP. Short-poll like the rail so the human's view tracks the executor without refresh.
const POLL_MS = 3000;

const STATUS: Record<string, { label: string; dot: string; text: string }> = {
  proposed: { label: "proposed", dot: "bg-proposed", text: "text-proposed-foreground" },
  ready: { label: "ready", dot: "bg-ink-soft", text: "text-ink-soft" },
  in_progress: { label: "in progress", dot: "bg-primary", text: "text-accent-deep" },
  blocked_on_decision: { label: "blocked", dot: "bg-proposed", text: "text-proposed-foreground" },
  in_verification: { label: "in verification", dot: "bg-primary", text: "text-accent-deep" },
  done: { label: "done", dot: "bg-confirmed", text: "text-confirmed-foreground" },
};

const RESULT: Record<string, { label: string; cls: string }> = {
  pass: { label: "pass", cls: "text-confirmed-foreground" },
  fail: { label: "fail", cls: "text-proposed-foreground" },
  needs_judgment: { label: "needs judgment", cls: "text-accent-deep" },
};

// status drives the left bar: green when it governs (done), amber when it wants the
// human (proposed / submitted / blocked), quiet otherwise.
function unitBar(status: string): string {
  if (status === "done") return "border-l-confirmed";
  if (["proposed", "in_verification", "blocked_on_decision"].includes(status))
    return "border-l-proposed";
  return "border-l-border";
}

function truncate(s: string, n = 52): string {
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}

export default function WorkUnits({
  initiativeId,
  acceptance,
}: {
  initiativeId: string;
  acceptance: AcceptanceCriterion[];
}) {
  const [units, setUnits] = useState<WorkUnit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, string>>({});

  const critText = (id: string) => acceptance.find((a) => a.id === id)?.text ?? id;

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/specs/${initiativeId}/units`, { cache: "no-store" });
      if (!res.ok) throw new Error(`couldn't load units (${res.status})`);
      setUnits(await res.json());
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

  async function act(unitId: string, action: "confirm" | "verdict", body?: object) {
    if (busy) return;
    setBusy(unitId);
    try {
      const res = await fetch(`/api/units/${unitId}/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      if (!res.ok) throw new Error(`${action} failed (${res.status})`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function renderUnit(u: WorkUnit) {
    const fb = (feedback[u.id] ?? "").trim();
    const working = busy === u.id;
    return (
      <li
        key={u.id}
        className={cn(
          "list-none rounded-md border border-l-[3px] bg-card/60 px-4 py-3.5",
          unitBar(u.status),
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest uppercase">
              <span className={cn("size-1.5 rounded-full", (STATUS[u.status] ?? STATUS.proposed).dot)} />
              <span className={(STATUS[u.status] ?? STATUS.proposed).text}>
                {(STATUS[u.status] ?? STATUS.proposed).label}
              </span>
            </span>
            <h3 className="mt-1.5 font-serif text-[17px] leading-snug">{u.title}</h3>
          </div>
          {u.status === "proposed" && (
            <Button
              size="sm"
              disabled={working}
              onClick={() => act(u.id, "confirm")}
              className="shrink-0 bg-confirmed text-white shadow-sm hover:bg-confirmed/90"
            >
              <Check /> Confirm
            </Button>
          )}
        </div>

        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{u.scope}</p>

        {u.criterion_ids.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 font-mono text-[10.5px] text-ink-faint">
            <ListChecks className="size-3" /> satisfies
            {u.criterion_ids.map((id) => (
              <span key={id} title={critText(id)} className="rounded bg-secondary px-1.5 py-0.5">
                {truncate(critText(id), 36)}
              </span>
            ))}
          </div>
        )}

        {u.progress_note && u.status !== "done" && (
          <p className="mt-2 text-[12.5px] text-ink-soft">
            <span className="font-mono text-[10px] tracking-wide text-ink-faint uppercase">
              progress ·{" "}
            </span>
            {u.progress_note}
          </p>
        )}

        {u.status === "blocked_on_decision" && (
          <p className="mt-2 flex items-center gap-1.5 font-mono text-[11px] text-proposed-foreground">
            <Link2 className="size-3" /> blocked on decision {u.blocked_on} — resolve it on the rail
          </p>
        )}

        {u.status === "in_progress" && u.verdict?.verdict === "changes_requested" && (
          <div className="mt-2.5 rounded border border-proposed/30 bg-proposed/10 px-3 py-2 text-[12.5px]">
            <span className="font-mono text-[10px] tracking-wide text-proposed-foreground uppercase">
              changes requested ·{" "}
            </span>
            {u.verdict.feedback}
          </div>
        )}

        {u.status === "in_verification" && u.submission && (
          <div className="mt-3 rounded-md border border-border bg-background/60 p-3.5">
            <p className="text-[13px] leading-relaxed">{u.submission.summary}</p>
            <ul className="mt-3 space-y-2">
              {u.submission.criteria_results.map((c, i) => (
                <li key={i} className="text-[12.5px] leading-snug">
                  <span className={cn("font-mono text-[10px] tracking-wide uppercase", RESULT[c.result]?.cls)}>
                    {RESULT[c.result]?.label ?? c.result}
                  </span>{" "}
                  <span className="text-foreground">{critText(c.criterion_id)}</span>
                  {c.evidence && <span className="mt-0.5 block text-ink-soft">— {c.evidence}</span>}
                </li>
              ))}
            </ul>
            <Textarea
              rows={2}
              placeholder="Feedback (required to request changes)"
              value={feedback[u.id] ?? ""}
              onChange={(e) => setFeedback((f) => ({ ...f, [u.id]: e.target.value }))}
              className="mt-3 text-[13px]"
            />
            <div className="mt-2.5 flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={working}
                onClick={() => act(u.id, "verdict", { verdict: "approved", feedback: fb })}
                className="bg-confirmed text-white shadow-sm hover:bg-confirmed/90"
              >
                <Check /> Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={working || fb.length === 0}
                title={fb.length === 0 ? "Add feedback first" : ""}
                onClick={() => act(u.id, "verdict", { verdict: "changes_requested", feedback: fb })}
              >
                <RotateCcw /> Request changes
              </Button>
            </div>
          </div>
        )}

        {u.status === "done" && (
          <p className="mt-2.5 flex items-center gap-1.5 text-[12.5px] text-confirmed-foreground">
            <Check className="size-3.5" /> approved{u.verdict?.feedback ? ` — ${u.verdict.feedback}` : ""}
          </p>
        )}
      </li>
    );
  }

  return (
    <section className="mt-10 animate-rise border-t border-border pt-7 [animation-delay:320ms]">
      <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
        <Hammer className="size-3.5" /> Work units
        <span className="font-normal tracking-normal text-ink-faint normal-case">
          · decomposed, built, verified — the loop closes here
        </span>
      </h2>

      {error && (
        <p className="mt-3 rounded-md border border-proposed/30 bg-proposed/10 px-3 py-1.5 font-mono text-xs text-proposed-foreground">
          {error}
        </p>
      )}

      {units !== null && units.length === 0 && !error && (
        <p className="mt-3 text-sm text-muted-foreground">
          No work units yet — the executor proposes them over MCP (
          <code className="font-mono text-[12px]">propose_unit</code>); you confirm them here.
        </p>
      )}

      <ul className="mt-4 space-y-2.5">{(units ?? []).map(renderUnit)}</ul>
    </section>
  );
}
