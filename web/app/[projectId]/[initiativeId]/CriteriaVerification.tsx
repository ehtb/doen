"use client";

import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, RotateCcw, ShieldCheck } from "lucide-react";
import type { AcceptanceCriterion } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useSpec } from "./spec-context";

// Verification status display config
const STATUS_CONFIG = {
  pending: {
    label: "pending",
    dot: "bg-border",
    text: "text-ink-faint",
    bar: "border-l-border",
  },
  evidence_submitted: {
    label: "evidence submitted",
    dot: "bg-primary",
    text: "text-accent-deep",
    bar: "border-l-primary",
  },
  verified: {
    label: "verified",
    dot: "bg-confirmed",
    text: "text-confirmed-foreground",
    bar: "border-l-confirmed",
  },
  changes_requested: {
    label: "changes requested",
    dot: "bg-proposed",
    text: "text-proposed-foreground",
    bar: "border-l-proposed",
  },
} as const;

function VerificationBadge({ status }: { status: AcceptanceCriterion["verification_status"] }) {
  const cfg = STATUS_CONFIG[status];
  return (
    <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest uppercase">
      <span className={cn("size-1.5 rounded-full", cfg.dot)} />
      <span className={cfg.text}>{cfg.label}</span>
    </span>
  );
}

function CriterionVerificationCard({ criterion }: { criterion: AcceptanceCriterion }) {
  const { spec, mutate, busy } = useSpec();
  const [feedback, setFeedback] = useState("");
  const [showActions, setShowActions] = useState(false);
  const status = criterion.verification_status ?? "pending";
  const cfg = STATUS_CONFIG[status];

  async function recordVerdict(verdict: "approved" | "changes_requested") {
    if (verdict === "changes_requested" && !feedback.trim()) return;
    await mutate(
      `/api/specs/${spec.initiative_id}/criteria/${criterion.id}/verdict`,
      "POST",
      { verdict, feedback: feedback.trim() || null },
    );
    setFeedback("");
    setShowActions(false);
  }

  return (
    <li
      className={cn(
        "list-none rounded-md border border-l-[3px] bg-card/60 px-3.5 py-3",
        cfg.bar,
        status === "changes_requested" && "bg-proposed/[0.04]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <VerificationBadge status={status} />
          <p className="mt-1.5 font-mono text-[12.5px] leading-relaxed text-foreground">
            {criterion.text}
            <span className="ml-1 text-ink-faint">[{criterion.verify?.kind}]</span>
          </p>
        </div>
      </div>

      {/* Evidence block — visible when submitted or reviewed */}
      {criterion.evidence && (
        <div className="mt-2.5 rounded-md border border-border bg-background/60 px-3 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
          <span className="mr-1.5 font-mono text-[10px] tracking-wide text-ink-faint uppercase">
            evidence ·
          </span>
          {criterion.evidence}
        </div>
      )}

      {/* Feedback from human when changes requested */}
      {criterion.feedback && status === "changes_requested" && (
        <p className="mt-2 font-mono text-[11.5px] text-proposed-foreground">
          <span className="mr-1 text-[10px] tracking-wide uppercase">feedback ·</span>
          {criterion.feedback}
        </p>
      )}

      {/* Human verdict actions — shown when evidence exists and not yet verified */}
      {status === "evidence_submitted" && (
        <div className="mt-3">
          {!showActions ? (
            <button
              type="button"
              onClick={() => setShowActions(true)}
              className="font-mono text-[10.5px] tracking-wide text-accent-deep underline-offset-4 hover:underline"
            >
              Review this criterion
            </button>
          ) : (
            <div className="space-y-2.5">
              <Textarea
                rows={2}
                placeholder="Feedback (required to request changes)"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                className="text-[13px]"
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => recordVerdict("approved")}
                  className="bg-confirmed text-white shadow-sm hover:bg-confirmed/90"
                >
                  <Check /> Approve
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || !feedback.trim()}
                  title={!feedback.trim() ? "Add feedback first" : ""}
                  onClick={() => recordVerdict("changes_requested")}
                >
                  <RotateCcw /> Request changes
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-ink-faint"
                  onClick={() => setShowActions(false)}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Verified state */}
      {status === "verified" && (
        <p className="mt-2 flex items-center gap-1.5 text-[12px] text-confirmed-foreground">
          <Check className="size-3.5" /> approved
          {criterion.feedback && <span className="text-ink-soft"> — {criterion.feedback}</span>}
        </p>
      )}
    </li>
  );
}

export default function CriteriaVerification({
  initiativeId,
}: {
  initiativeId: string;
}) {
  const { spec, mutate, busy } = useSpec();
  const criteria = spec.acceptance;
  const isPostBuild = spec.state === "learning" || spec.state === "complete";
  const [collapsed, setCollapsed] = useState(isPostBuild);
  // Collapse when state transitions into learning/complete on a live page (SWR update
  // doesn't remount client components, so the useState initialiser won't re-run).
  useEffect(() => {
    if (isPostBuild) setCollapsed(true);
  }, [isPostBuild]);

  if (criteria.length === 0) return null;

  const verified = criteria.filter((c) => c.verification_status === "verified").length;
  const withEvidence = criteria.filter(
    (c) => c.verification_status === "evidence_submitted" || c.verification_status === "verified",
  ).length;
  const allVerified = verified === criteria.length;
  const verifyPct = Math.round((verified / criteria.length) * 100);
  const nonVerified = criteria.filter((c) => c.verification_status !== "verified");

  async function approveAll() {
    for (const c of nonVerified) {
      await mutate(
        `/api/specs/${spec.initiative_id}/criteria/${c.id}/verdict`,
        "POST",
        { verdict: "approved", feedback: null },
      );
    }
  }

  return (
    <section
      id="criteria-verification"
      className="mt-10 animate-rise scroll-mt-6 border-t border-border pt-7 [animation-delay:320ms]"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={isPostBuild ? () => setCollapsed((c) => !c) : undefined}
          className={cn(
            "flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase",
            isPostBuild && "cursor-pointer hover:text-foreground",
          )}
        >
          {isPostBuild ? (
            collapsed ? (
              <ChevronRight className="size-3.5" />
            ) : (
              <ChevronDown className="size-3.5" />
            )
          ) : (
            <ShieldCheck className="size-3.5" />
          )}
          Verification
          <span className="font-normal tracking-normal text-ink-faint normal-case">
            · criteria verified by evidence
          </span>
        </button>

        <div className="flex items-center gap-3">
          {/* Approve-all escape hatch — agent should normally do this */}
          {!allVerified && (
            <span className="flex items-center gap-1.5">
              <span className="font-mono text-[10px] text-ink-faint">
                agent should verify ·
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={approveAll}
                className="font-mono text-[10px] tracking-wide text-accent-deep underline-offset-4 hover:underline disabled:opacity-40"
              >
                approve all
              </button>
            </span>
          )}
          {/* Aggregate progress indicator */}
          <span
            className={cn(
              "flex items-center gap-1.5 font-mono text-[10.5px] tabular-nums",
              allVerified ? "text-confirmed-foreground" : "text-ink-soft",
            )}
          >
            {allVerified && <Check className="size-3" />}
            {verified} / {criteria.length} verified
          </span>
        </div>
      </div>

      {!collapsed && (
        <>
          {/* Progress bar */}
          {withEvidence > 0 && (
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-border/70">
              <div
                className="h-full rounded-full bg-confirmed transition-all duration-500 ease-out"
                style={{ width: `${verifyPct}%` }}
              />
            </div>
          )}

          <ul className="mt-4 space-y-2.5">
            {criteria.map((c) => (
              <CriterionVerificationCard key={c.id} criterion={c} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
