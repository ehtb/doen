"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { BookOpen, Bot, Brain, Check, GitBranch, Loader2, Sparkles, Tag, Trash2, User, X } from "lucide-react";

import type { Decision, Heuristic, HeuristicDraftResult, HeuristicProposal, LearnReview, LearningItem, OutcomeDraft, RationaleClaim } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// BD-13: source type badge for rationale claims.
function SourceBadge({ sourceType, sourceId }: { sourceType: string; sourceId: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-card/80 border border-border px-1.5 py-0.5 font-mono text-[9.5px] tracking-wide text-ink-faint">
      {sourceType} · {sourceId}
    </span>
  );
}

// BD-13: rationale claims — human confirms before memory write.
function RationaleClaims({
  claims,
  onChange,
}: {
  claims: RationaleClaim[];
  onChange: (claims: RationaleClaim[]) => void;
}) {
  if (claims.length === 0) return null;

  return (
    <div className="mt-4 rounded-lg border border-border bg-card/40 p-4">
      <p className="font-mono text-[10px] tracking-widest text-ink-faint uppercase">
        Cause-effect rationale
        <span className="ml-1.5 normal-case font-normal tracking-normal text-ink-faint">
          · each claim is traceable to a record entry — remove any you disagree with
        </span>
      </p>
      <ul className="mt-2.5 space-y-2">
        {claims.map((c, i) => (
          <li key={i} className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-[12.5px] leading-snug text-foreground">{c.claim}</p>
              <div className="mt-0.5">
                <SourceBadge sourceType={c.source_type} sourceId={c.source_id} />
              </div>
            </div>
            <button
              type="button"
              title="Remove this claim"
              onClick={() => onChange(claims.filter((_, j) => j !== i))}
              className="mt-0.5 shrink-0 rounded p-0.5 text-ink-faint hover:text-proposed-foreground hover:bg-proposed/10 transition-colors"
            >
              <Trash2 className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>
      {claims.length > 0 && (
        <p className="mt-2.5 font-mono text-[10px] tracking-wide text-ink-faint">
          {claims.length} claim{claims.length !== 1 ? "s" : ""} — will be written to memory on confirm
        </p>
      )}
    </div>
  );
}

// BD-13: decision row with agent-resolved / human-resolved visual distinction.
function DecisionRow({ d }: { d: Decision }) {
  const isAgentResolved = d.resolver_type === "agent";
  return (
    <li className="text-[12.5px] leading-snug">
      <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-ink-faint">
        <GitBranch className="size-3" />
        {isAgentResolved ? (
          <>
            <Bot className="size-3 text-ink-faint" />
            <span className="text-ink-faint">auto-resolved by discretion auditor</span>
          </>
        ) : (
          <>
            <User className="size-3 text-ink-faint" />
            <span>human judgment</span>
          </>
        )}
      </span>
      <span className="mt-0.5 block font-mono text-[10.5px] text-ink-soft">{d.question}</span>
      <span className="mt-0.5 block text-foreground">
        <span className={isAgentResolved ? "text-ink-soft" : "text-confirmed-foreground"}>
          {d.chosen}
        </span>
        {d.rationale && (
          <span className="text-ink-soft">
            {" "}
            —{" "}
            {isAgentResolved
              ? d.rationale.replace(/^\[Discretion Auditor\] /, "")
              : d.rationale}
          </span>
        )}
      </span>
    </li>
  );
}

// BD-17: heuristic confirmation panel — shown after the outcome is captured so the human
// reviews proposed heuristics before they enter long-term memory.
function HeuristicConfirmation({
  initiativeId,
  onDone,
}: {
  initiativeId: string;
  onDone: (written: Heuristic[]) => void;
}) {
  const [phase, setPhase] = useState<"idle" | "drafting" | "reviewing" | "confirming" | "done">("idle");
  const [proposals, setProposals] = useState<HeuristicProposal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<Heuristic[]>([]);

  async function draft() {
    setPhase("drafting");
    setError(null);
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/learn/heuristics/draft`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`couldn't draft heuristics (${res.status})`);
      const data: HeuristicDraftResult = await res.json();
      if (data.proposals.length === 0) {
        onDone([]);
        return;
      }
      setProposals(data.proposals);
      setPhase("reviewing");
    } catch (e) {
      setError((e as Error).message);
      setPhase("idle");
    }
  }

  function removeProposal(i: number) {
    setProposals((prev) => prev.filter((_, j) => j !== i));
  }

  async function confirmAll() {
    if (!proposals.length) {
      onDone([]);
      return;
    }
    setPhase("confirming");
    setError(null);
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/learn/heuristics/confirm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ proposals }),
      });
      if (!res.ok) throw new Error(`couldn't save heuristics (${res.status})`);
      const written: Heuristic[] = await res.json();
      setConfirmed(written);
      onDone(written);
    } catch (e) {
      setError((e as Error).message);
      setPhase("reviewing");
    }
  }

  if (phase === "idle") {
    return (
      <div className="mt-4 flex items-center gap-3 rounded-lg border border-dashed border-border px-4 py-3">
        <Brain className="size-4 shrink-0 text-ink-faint" />
        <p className="text-[12.5px] text-ink-soft flex-1">
          Extract transferable heuristics from this initiative for the knowledge flywheel.
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={draft}
          className="h-7 px-2.5 font-mono text-[11px] tracking-wide shrink-0"
        >
          <Sparkles className="size-3" /> Draft heuristics
        </Button>
      </div>
    );
  }

  if (phase === "drafting") {
    return (
      <div className="mt-4 flex items-center gap-2 rounded-lg border border-border px-4 py-3 text-ink-faint">
        <Loader2 className="size-3.5 animate-spin" />
        <span className="text-[12.5px]">Extracting heuristics…</span>
      </div>
    );
  }

  if (phase === "reviewing" && proposals.length > 0) {
    return (
      <div className="mt-4 rounded-lg border border-border bg-card/50 p-4">
        <p className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
          <Brain className="size-3" /> Proposed heuristics
          <span className="ml-1.5 normal-case font-normal tracking-normal text-ink-faint">
            · remove any you disagree with before confirming
          </span>
        </p>
        {error && (
          <p className="mt-2 text-[11.5px] text-red-500">{error}</p>
        )}
        <ul className="mt-3 space-y-2.5">
          {proposals.map((p, i) => (
            <li key={i} className="flex items-start gap-2 rounded-md border border-border bg-background/60 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] leading-snug text-foreground">{p.rule}</p>
                {p.tags.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {p.tags.map((t) => (
                      <span key={t} className="inline-flex items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 font-mono text-[9.5px] text-ink-faint">
                        <Tag className="size-2.5" />{t}
                      </span>
                    ))}
                  </div>
                )}
                {p.replaces && (
                  <p className="mt-1 font-mono text-[9.5px] text-amber-600">
                    supersedes {p.replaces}
                  </p>
                )}
              </div>
              <button
                type="button"
                title="Remove this heuristic"
                onClick={() => removeProposal(i)}
                className="mt-0.5 shrink-0 rounded p-0.5 text-ink-faint hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
              >
                <X className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex items-center gap-2">
          <Button
            size="sm"
            disabled={["confirming", "done"].includes(phase)}
            onClick={confirmAll}
            className="bg-confirmed text-white shadow-sm hover:bg-confirmed/90 h-7 px-3 font-mono text-[11px]"
          >
            <Check className="size-3" /> Confirm {proposals.length} heuristic{proposals.length !== 1 ? "s" : ""}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDone([])}
            className="h-7 px-2.5 font-mono text-[11px] text-ink-faint"
          >
            Skip
          </Button>
        </div>
      </div>
    );
  }

  return null;
}


// BD-17: display a confirmed heuristic entry — visually distinct from narrative memory (item_b04eb0385be9).
function HeuristicEntry({ h }: { h: Heuristic }) {
  return (
    <div className="rounded-md border border-l-[3px] border-l-violet-400 bg-violet-50/50 dark:bg-violet-950/20 px-4 py-3">
      <p className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest text-violet-600 dark:text-violet-400 uppercase">
        <Brain className="size-3" /> heuristic
        {h.tags.length > 0 && (
          <span className="ml-1 flex gap-1">
            {h.tags.map((t) => (
              <span key={t} className="rounded bg-violet-100 dark:bg-violet-900/40 px-1 py-0.5 font-mono text-[9px] text-violet-600 dark:text-violet-400">
                {t}
              </span>
            ))}
          </span>
        )}
        {h.superseded_by && (
          <span className="ml-1 text-amber-600 normal-case tracking-normal font-normal">
            [superseded by {h.superseded_by}]
          </span>
        )}
      </p>
      <p className="mt-1.5 text-[13px] leading-relaxed">{h.rule}</p>
      {h.replaces && (
        <p className="mt-1 font-mono text-[9.5px] text-ink-faint">replaces {h.replaces}</p>
      )}
    </div>
  );
}


// BD-25: auto-approved learnings — passive summary, not a review queue.
function AutoApprovedLearnings({ items }: { items: LearningItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-3 rounded-lg border border-border bg-card/30 p-3.5">
      <p className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
        <Bot className="size-3" /> auto-approved learnings
        <span className="ml-1.5 normal-case font-normal tracking-normal text-ink-faint">
          · high-confidence match to spec — writing to memory without review
        </span>
      </p>
      <ul className="mt-2 space-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-[12.5px] text-ink-soft">
            <span className="mt-0.5 shrink-0 font-mono text-ink-faint">–</span>
            <span>{item.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// BD-25: needs-review learnings — human confirms which ones to write to memory.
function NeedsReviewLearnings({
  items,
  approved,
  onChange,
}: {
  items: LearningItem[];
  approved: Set<number>;
  onChange: (approved: Set<number>) => void;
}) {
  if (items.length === 0) return null;

  function toggle(i: number) {
    const next = new Set(approved);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    onChange(next);
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-card/40 p-3.5">
      <p className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
        <BookOpen className="size-3" /> learnings to review
        <span className="ml-1.5 normal-case font-normal tracking-normal text-ink-faint">
          · uncheck any you don&apos;t want written to memory
        </span>
      </p>
      <ul className="mt-2 space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2">
            <button
              type="button"
              onClick={() => toggle(i)}
              className={`mt-0.5 shrink-0 rounded p-0.5 transition-colors ${
                approved.has(i)
                  ? "text-confirmed-foreground hover:text-ink-soft"
                  : "text-ink-faint hover:text-foreground"
              }`}
            >
              {approved.has(i) ? <Check className="size-3.5" /> : <X className="size-3.5" />}
            </button>
            <span className={`text-[12.5px] leading-snug ${approved.has(i) ? "text-foreground" : "text-ink-faint line-through"}`}>
              {item.text}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 font-mono text-[10px] tracking-wide text-ink-faint">
        {[...approved].length} of {items.length} selected
      </p>
    </div>
  );
}


export default function LearnStage({
  initiativeId,
  intent,
  initiativeType,
}: {
  initiativeId: string;
  intent: string;
  initiativeType: "engineering" | "research";
}) {
  const isResearch = initiativeType === "research";
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState("");
  const [conclusion, setConclusion] = useState("");
  const [busy, setBusy] = useState(false);
  const [drafting, setDrafting] = useState(false);
  // BD-13: rationale claims from the AI draft — human must confirm/remove before submit.
  const [rationaleClaims, setRationaleClaims] = useState<RationaleClaim[]>([]);
  // BD-25: structured learnings from the AI draft.
  const [autoApprovedLearnings, setAutoApprovedLearnings] = useState<LearningItem[]>([]);
  const [needsReviewLearnings, setNeedsReviewLearnings] = useState<LearningItem[]>([]);
  const [approvedReviewIndices, setApprovedReviewIndices] = useState<Set<number>>(new Set());
  // BD-17: heuristics written for this session (post-confirm).
  const [sessionHeuristics, setSessionHeuristics] = useState<Heuristic[]>([]);
  const [showHeuristicPanel, setShowHeuristicPanel] = useState(false);
  // The outcome form is the active surface only when a reflection is being written. After it's
  // captured the form closes; an explicit "Add another reflection" reopens it with blank fields
  // so a stray re-click can't duplicate the memory.
  const [showForm, setShowForm] = useState(true);
  const [initializedForm, setInitializedForm] = useState(false);
  const router = useRouter();

  const { data: review, mutate: refreshReview } = useSWR<LearnReview>(
    `/api/initiatives/${initiativeId}/learn`,
    (url: string) => fetch(url, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(`couldn't load the review (${r.status})`);
      return r.json();
    }),
    { refreshInterval: 3000, dedupingInterval: 2500, revalidateOnFocus: false },
  );

  // On first review load, close the form if a memory already exists (revisiting a spec that has
  // captured learn). Subsequent review updates (the poll) don't reopen it.
  useEffect(() => {
    if (!initializedForm && review !== undefined) {
      setShowForm(review.memory.length === 0);
      setInitializedForm(true);
    }
  }, [review, initializedForm]);

  async function draftWithAI() {
    if (drafting) return;
    setDrafting(true);
    setError(null);
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/learn/draft`, { method: "POST" });
      if (!res.ok) throw new Error(`couldn't draft the outcome (${res.status})`);
      const draft: OutcomeDraft = await res.json();
      setSummary(draft.summary ?? "");
      if (draft.conclusion) setConclusion(draft.conclusion);
      // BD-25: populate structured learnings — auto-approved shown passively, needs-review as checklist.
      setAutoApprovedLearnings(draft.auto_approved_learnings ?? []);
      const reviewItems = draft.needs_review_learnings ?? [];
      setNeedsReviewLearnings(reviewItems);
      // Default: all needs-review items are pre-approved (human unchecks to remove).
      setApprovedReviewIndices(new Set(reviewItems.map((_, i) => i)));
      // BD-13: populate rationale claims from the draft — human reviews before submit.
      setRationaleClaims(draft.rationale_claims ?? []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDrafting(false);
    }
  }

  async function submit() {
    if (busy) return;
    setBusy(true);
    try {
      // BD-25: build human-approved learnings from the checked needs-review items.
      const humanApproved = needsReviewLearnings
        .filter((_, i) => approvedReviewIndices.has(i))
        .map((item) => item.text);
      const res = await fetch(`/api/initiatives/${initiativeId}/learn`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          summary,
          conclusion: conclusion.trim() || undefined,
          auto_approved_learnings: autoApprovedLearnings.map((item) => item.text),
          human_approved_learnings: humanApproved,
          rationale_claims: rationaleClaims,
        }),
      });
      if (!res.ok) throw new Error(`couldn't save the outcome (${res.status})`);
      await refreshReview(await res.json(), { revalidate: false });
      // close the form so the captured memory above reads as the resting state, and clear the
      // fields so a stray re-open isn't pre-populated with the prior reflection.
      setSummary("");
      setConclusion("");
      setRationaleClaims([]);
      setAutoApprovedLearnings([]);
      setNeedsReviewLearnings([]);
      setApprovedReviewIndices(new Set());
      setShowForm(false);
      // BD-17: after the outcome is captured, offer heuristic extraction.
      setShowHeuristicPanel(true);
      router.refresh(); // capturing learn may complete the initiative — reflect the inferred state
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const decisions = review?.decisions ?? [];
  const memory = review?.memory ?? [];

  return (
    <section id="learn" className="mt-12 animate-rise scroll-mt-6 border-t border-border pt-8 [animation-delay:360ms]">

      {/* Section header */}
      <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
        <BookOpen className="size-3.5" />
        {isResearch ? "Reflect" : "Learn"}
        <span className="font-normal tracking-normal text-ink-faint normal-case">
          · {isResearch
            ? "what the investigation found and concluded"
            : "what happened vs. what was intended — then remember it"}
        </span>
      </h2>

      {error && (
        <p className="mt-4 rounded-md border border-proposed/30 bg-proposed/10 px-3 py-1.5 font-mono text-xs text-proposed-foreground">
          {error}
        </p>
      )}

      {/* Context — intent + decisions, open layout (no cramped card) */}
      <div className="mt-6 space-y-6">
        <div>
          <p className="mb-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
            {isResearch ? "Research question" : "Intent"}
          </p>
          <p className="text-[14px] leading-relaxed text-foreground">{intent}</p>
        </div>

        {/* Decisions */}
        {(review?.decisions.length ?? 0) > 0 && (
          <div>
            <p className="mb-2 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
              Decisions made
            </p>
            {(() => {
              const humanDec = (review?.decisions ?? []).filter(d => d.resolver_type !== "agent");
              const agentDec = (review?.decisions ?? []).filter(d => d.resolver_type === "agent");
              return (
                <ul className="space-y-3">
                  {humanDec.map(d => <DecisionRow key={d.id} d={d} />)}
                  {agentDec.length > 0 && (
                    <>
                      {humanDec.length > 0 && (
                        <li className="border-t border-border/50 pt-2">
                          <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
                            <Bot className="size-3" /> auto-resolved by discretion auditor ({agentDec.length})
                          </span>
                        </li>
                      )}
                      {agentDec.map(d => <DecisionRow key={d.id} d={d} />)}
                    </>
                  )}
                </ul>
              );
            })()}
          </div>
        )}
        {(review !== undefined) && (review?.decisions.length === 0) && (
          <p className="text-[13px] text-ink-faint">No decisions were escalated.</p>
        )}
      </div>

      {/* Captured memory */}
      {memory.length > 0 && (
        <div className="mt-8 space-y-3">
          {memory.map((m) => (
            <div key={m.id} className="rounded-xl border border-l-[3px] border-l-confirmed bg-card/60 px-5 py-4">
              <p className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest text-confirmed-foreground uppercase">
                <Check className="size-3" /> remembered
              </p>

              {/* Research: show conclusion prominently if present */}
              {isResearch && (m.outcome as any)?.conclusion && (
                <div className="mt-3">
                  <p className="mb-1 font-mono text-[10px] tracking-widest text-ink-faint uppercase">Conclusion</p>
                  <p className="text-[14px] leading-relaxed text-foreground whitespace-pre-wrap">
                    {(m.outcome as any).conclusion}
                  </p>
                </div>
              )}

              <div className={isResearch && (m.outcome as any)?.conclusion ? "mt-4" : "mt-2"}>
                {isResearch && (m.outcome as any)?.conclusion && (
                  <p className="mb-1 font-mono text-[10px] tracking-widest text-ink-faint uppercase">Retrospective</p>
                )}
                <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-foreground">{m.summary}</p>
              </div>

              {/* Learnings */}
              {m.learnings && !(m.outcome as any)?.learning_approvals && (
                <p className="mt-3 text-[12.5px] leading-relaxed text-ink-soft">
                  <span className="font-mono text-[10px] tracking-wide text-ink-faint uppercase">learnings · </span>
                  {m.learnings}
                </p>
              )}
              {(m.outcome as any)?.learning_approvals && (
                <div className="mt-3">
                  <p className="font-mono text-[10px] tracking-wide text-ink-faint uppercase">Learnings</p>
                  <ul className="mt-1.5 space-y-1.5">
                    {((m.outcome as any).learning_approvals as Array<{ text: string; approved_by: string }>).map((la, i) => (
                      <li key={i} className="flex items-start gap-2 text-[12.5px]">
                        <span className="mt-0.5 font-mono text-ink-faint shrink-0">–</span>
                        <span className="flex-1 text-ink-soft">{la.text}</span>
                        {la.approved_by === "auto" ? (
                          <span className="shrink-0 inline-flex items-center gap-0.5 rounded bg-card border border-border px-1 py-0.5 font-mono text-[9px] text-ink-faint">
                            <Bot className="size-2.5" /> auto
                          </span>
                        ) : (
                          <span className="shrink-0 inline-flex items-center gap-0.5 rounded bg-confirmed/10 border border-confirmed/20 px-1 py-0.5 font-mono text-[9px] text-confirmed-foreground">
                            <User className="size-2.5" /> human
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Active form */}
      {showForm ? (
        <div className="mt-8">
          <div className="flex items-center justify-between gap-3">
            <p className="font-mono text-[11px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
              {memory.length > 0
                ? "Add another reflection"
                : isResearch ? "Conclusion & retrospective" : "Outcome summary"}
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={drafting || busy}
              onClick={draftWithAI}
              className="h-7 px-3 font-mono text-[11px] tracking-wide shrink-0"
            >
              {drafting ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {drafting ? "Drafting…" : "Draft with AI"}
            </Button>
          </div>

          {/* Research: conclusion field (the primary artifact) */}
          {isResearch && (
            <div className="mt-4">
              <p className="mb-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
                Conclusion
                <span className="ml-1.5 normal-case font-normal tracking-normal">
                  — direct answer to the research question
                </span>
              </p>
              <Textarea
                rows={5}
                value={conclusion}
                onChange={(e) => setConclusion(e.target.value)}
                placeholder="What did this investigation conclude? Answer the original question directly."
                className="bg-card text-[13.5px] leading-relaxed"
              />
            </div>
          )}

          {/* Retrospective / outcome summary */}
          <div className="mt-4">
            {isResearch && (
              <p className="mb-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
                Retrospective
                <span className="ml-1.5 normal-case font-normal tracking-normal">
                  — how the investigation went
                </span>
              </p>
            )}
            <Textarea
              rows={isResearch ? 4 : 7}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder={
                memory.length > 0
                  ? "A reflection — what surprised you, what you'd carry forward, what you'd do differently."
                  : isResearch
                  ? "How the investigation went — methodology, what you tried, what surprised you."
                  : "What did this initiative actually produce, against its intent?"
              }
              className="bg-card text-[13px]"
            />
          </div>

          {/* Structured learnings */}
          <AutoApprovedLearnings items={autoApprovedLearnings} />
          <NeedsReviewLearnings
            items={needsReviewLearnings}
            approved={approvedReviewIndices}
            onChange={setApprovedReviewIndices}
          />

          {/* Rationale claims */}
          <RationaleClaims claims={rationaleClaims} onChange={setRationaleClaims} />

          {/* Submit */}
          <div className="mt-5 flex items-center gap-3">
            <Button
              disabled={busy || (!summary.trim() && (!isResearch || !conclusion.trim()))}
              onClick={submit}
              className="bg-confirmed text-white shadow-sm hover:bg-confirmed/90"
            >
              <Sparkles />
              {memory.length > 0 ? "Capture & embed" : isResearch ? "Complete & remember" : "Complete & remember"}
            </Button>
            {memory.length > 0 && (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setSummary("");
                  setConclusion("");
                  setRationaleClaims([]);
                  setAutoApprovedLearnings([]);
                  setNeedsReviewLearnings([]);
                  setApprovedReviewIndices(new Set());
                  setShowForm(false);
                }}
              >
                Cancel
              </Button>
            )}
            <span className="font-mono text-[10.5px] text-ink-faint">
              writes an embedded memory the next initiative can retrieve
            </span>
          </div>
        </div>
      ) : memory.length > 0 ? (
        <div className="mt-6 flex items-center gap-3 rounded-xl border border-confirmed/30 bg-confirmed/5 px-4 py-3.5">
          <Sparkles className="size-4 shrink-0 text-confirmed-foreground" />
          <p className="text-[13px] text-foreground">
            {memory.length === 1 ? "Learning captured." : `${memory.length} reflections captured.`}{" "}
            <span className="text-ink-faint">
              The spec is complete and the memory is embedded for the next initiative.
            </span>
          </p>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto h-8 px-3"
            onClick={() => {
              setSummary("");
              setConclusion("");
              setRationaleClaims([]);
              setAutoApprovedLearnings([]);
              setNeedsReviewLearnings([]);
              setApprovedReviewIndices(new Set());
              setShowForm(true);
            }}
          >
            Add another reflection
          </Button>
        </div>
      ) : null}

      {/* Heuristic extraction */}
      {showHeuristicPanel && !showForm && memory.length > 0 && (
        <HeuristicConfirmation
          initiativeId={initiativeId}
          onDone={(written) => {
            setSessionHeuristics(written);
            setShowHeuristicPanel(false);
          }}
        />
      )}

      {/* Confirmed heuristics */}
      {sessionHeuristics.length > 0 && (
        <div className="mt-5 space-y-2">
          {sessionHeuristics.map((h) => (
            <HeuristicEntry key={h.id} h={h} />
          ))}
        </div>
      )}

      {/* Skip */}
      {memory.length === 0 && <SkipReflection initiativeId={initiativeId} />}

    </section>
  );
}

function SkipReflection({ initiativeId }: { initiativeId: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function skip() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/complete-without-learnings`, {
        method: "POST",
      });
      if (res.ok) {
        router.refresh();
      }
    } finally {
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="font-mono text-[10.5px] tracking-wide text-ink-faint underline-offset-4 hover:text-proposed-foreground hover:underline"
        >
          Skip reflection and complete
        </button>
      </div>
    );
  }

  return (
    <div className="mt-4 animate-rise rounded-md border border-proposed/30 bg-proposed/5 px-3.5 py-3 text-[12.5px]">
      <p className="font-mono text-[10.5px] font-semibold tracking-wide text-proposed-foreground uppercase">
        Skipping reflection — nothing will be written to memory for this initiative.
      </p>
      <p className="mt-1 text-ink-soft">
        Future initiatives won&apos;t be able to learn from this one. Are you sure?
      </p>
      <div className="mt-2.5 flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={skip}
          className="font-mono text-[10.5px] tracking-wide text-proposed-foreground underline-offset-4 hover:underline disabled:opacity-50"
        >
          Yes, complete without memory
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="font-mono text-[10.5px] tracking-wide text-ink-faint underline-offset-4 hover:underline"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
