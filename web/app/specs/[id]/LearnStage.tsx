"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, BookOpen, Check, GitBranch, Sparkles } from "lucide-react";

import type { AcceptanceCriterion, LearnReview } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

// Pre-populate the outcome as a draft the human corrects (discretion: correction over
// authoring). Seeded from the intent + acceptance criteria — the human edits it into
// what actually happened.
function buildDraft(intent: string, acceptance: AcceptanceCriterion[]): string {
  const goals = acceptance.map((a) => `- ${a.text}`).join("\n");
  return [
    "What we set out to do:",
    intent.trim(),
    "",
    "What actually happened (edit — outcome against each criterion):",
    goals,
  ].join("\n");
}

export default function LearnStage({
  initiativeId,
  intent,
  acceptance,
}: {
  initiativeId: string;
  intent: string;
  acceptance: AcceptanceCriterion[];
}) {
  const [review, setReview] = useState<LearnReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState(() => buildDraft(intent, acceptance));
  const [learnings, setLearnings] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/learn`, { cache: "no-store" });
      if (!res.ok) throw new Error(`couldn't load the review (${res.status})`);
      setReview(await res.json());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [initiativeId]);

  useEffect(() => {
    load();
  }, [load]);

  async function submit() {
    if (busy || !summary.trim()) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/learn`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ summary, learnings: learnings.trim() || null }),
      });
      if (!res.ok) throw new Error(`couldn't save the outcome (${res.status})`);
      setReview(await res.json());
      router.refresh(); // reflect stage -> learn in the stepper
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const units = review?.units ?? [];
  const incomplete = units.filter((u) => u.status !== "done");
  const decisions = review?.decisions ?? [];
  const memory = review?.memory ?? [];

  return (
    <section className="mt-10 animate-rise border-t border-border pt-7 [animation-delay:360ms]">
      <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
        <BookOpen className="size-3.5" /> Learn
        <span className="font-normal tracking-normal text-ink-faint normal-case">
          · what happened vs. what was intended — then remember it
        </span>
      </h2>

      {error && (
        <p className="mt-3 rounded-md border border-proposed/30 bg-proposed/10 px-3 py-1.5 font-mono text-xs text-proposed-foreground">
          {error}
        </p>
      )}

      {/* --- the review (a4): intent, the calls made, and how each unit landed --- */}
      <div className="mt-4 rounded-lg border border-border bg-card/50 p-4">
        <p className="font-mono text-[10px] tracking-widest text-ink-faint uppercase">Intent</p>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{intent}</p>

        <p className="mt-4 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
          Decisions made
        </p>
        {decisions.length === 0 ? (
          <p className="mt-1 text-[13px] text-ink-faint">No decisions were escalated.</p>
        ) : (
          <ul className="mt-1.5 space-y-2">
            {decisions.map((d) => (
              <li key={d.id} className="text-[12.5px] leading-snug">
                <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-ink-faint">
                  <GitBranch className="size-3" /> {d.question}
                </span>
                <span className="mt-0.5 block text-foreground">
                  <span className="text-confirmed-foreground">{d.chosen}</span>
                  {d.rationale && <span className="text-ink-soft"> — {d.rationale}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}

        <p className="mt-4 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
          Unit outcomes
        </p>
        {units.length === 0 ? (
          <p className="mt-1 text-[13px] text-ink-faint">No work units were decomposed.</p>
        ) : (
          <ul className="mt-1.5 space-y-1.5">
            {units.map((u) => (
              <li key={u.id} className="flex items-start gap-2 text-[12.5px] leading-snug">
                <span
                  className={cn(
                    "mt-0.5 font-mono text-[10px] tracking-wide uppercase",
                    u.status === "done" ? "text-confirmed-foreground" : "text-proposed-foreground",
                  )}
                >
                  {u.status === "done" ? "done" : u.status.replace(/_/g, " ")}
                </span>
                <span className="text-foreground">
                  {u.title}
                  {u.verdict?.feedback && (
                    <span className="text-ink-soft"> — {u.verdict.feedback}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* --- soft gate (constraint 8 / D1->b): warn, never block --- */}
      {incomplete.length > 0 && (
        <p className="mt-3 flex items-center gap-2 rounded-md border border-proposed/30 bg-proposed/10 px-3 py-2 text-[12.5px] text-proposed-foreground">
          <AlertTriangle className="size-3.5 shrink-0" />
          {incomplete.length} of {units.length} units are not yet verified — you can still close
          out; their learnings are worth capturing.
        </p>
      )}

      {/* --- captured memory (after submit / on revisit) --- */}
      {memory.length > 0 && (
        <div className="mt-4 space-y-2">
          {memory.map((m) => (
            <div
              key={m.id}
              className="rounded-md border border-l-[3px] border-l-confirmed bg-card/60 px-4 py-3"
            >
              <p className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest text-confirmed-foreground uppercase">
                <Check className="size-3" /> remembered
              </p>
              <p className="mt-1.5 text-[13px] leading-relaxed whitespace-pre-wrap">{m.summary}</p>
              {m.learnings && (
                <p className="mt-2 text-[12.5px] leading-relaxed text-ink-soft">
                  <span className="font-mono text-[10px] tracking-wide text-ink-faint uppercase">
                    learnings ·{" "}
                  </span>
                  {m.learnings}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* --- the outcome form (a5) --- */}
      <div className="mt-4 rounded-lg border border-border bg-background/60 p-4">
        <p className="font-mono text-[10px] tracking-widest text-ink-faint uppercase">
          {memory.length > 0 ? "Add another reflection" : "Outcome summary"}
        </p>
        <Textarea
          rows={7}
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="What did this initiative actually produce, against its intent?"
          className="mt-2 text-[13px]"
        />
        <p className="mt-3 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
          Learnings
        </p>
        <Textarea
          rows={3}
          value={learnings}
          onChange={(e) => setLearnings(e.target.value)}
          placeholder="What would you carry into the next initiative? (optional)"
          className="mt-2 text-[13px]"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button
            disabled={busy || !summary.trim()}
            onClick={submit}
            className="bg-confirmed text-white shadow-sm hover:bg-confirmed/90"
          >
            <Sparkles /> {memory.length > 0 ? "Capture & embed" : "Complete & remember"}
          </Button>
          <span className="font-mono text-[10.5px] text-ink-faint">
            writes an embedded memory the next initiative can retrieve
          </span>
        </div>
      </div>
    </section>
  );
}
