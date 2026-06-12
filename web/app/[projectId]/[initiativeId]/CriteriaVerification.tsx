"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  HelpCircle,
  PenLine,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { AcceptanceCriterion } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useSpec } from "./spec-context";

const STATUS_CONFIG = {
  pending: {
    label: "pending",
    dot: "bg-border",
    text: "text-ink-faint",
    bar: "border-l-border",
    card: "",
  },
  evidence_submitted: {
    label: "evidence submitted",
    dot: "bg-primary",
    text: "text-accent-deep",
    bar: "border-l-primary",
    card: "bg-primary/[0.02]",
  },
  verified: {
    label: "verified",
    dot: "bg-confirmed",
    text: "text-confirmed-foreground",
    bar: "border-l-confirmed",
    card: "bg-confirmed/[0.03]",
  },
  changes_requested: {
    label: "changes requested",
    dot: "bg-proposed",
    text: "text-proposed-foreground",
    bar: "border-l-proposed",
    card: "bg-proposed/[0.04]",
  },
} as const;

function VerificationBadge({
  status,
  isResearch,
}: {
  status: AcceptanceCriterion["verification_status"];
  isResearch?: boolean;
}) {
  const cfg = STATUS_CONFIG[status];
  const label =
    isResearch && status === "evidence_submitted" ? "findings submitted" : cfg.label;
  return (
    <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest uppercase">
      <span className={cn("size-1.5 rounded-full", cfg.dot)} />
      <span className={cfg.text}>{label}</span>
    </span>
  );
}

function VerifyKindPill({ kind }: { kind?: string }) {
  if (!kind) return null;
  return (
    <span className="inline-block rounded bg-muted/70 px-1.5 py-0.5 font-mono text-[9.5px] tracking-wide text-ink-faint">
      {kind.replace(/_/g, " ")}
    </span>
  );
}

function CriterionVerificationCard({
  criterion,
  isResearch,
}: {
  criterion: AcceptanceCriterion;
  isResearch?: boolean;
}) {
  const { spec, mutate, busy } = useSpec();
  const [feedback, setFeedback] = useState("");
  const [showActions, setShowActions] = useState(false);
  const [showOverride, setShowOverride] = useState(false);
  const [overrideFeedback, setOverrideFeedback] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [manualText, setManualText] = useState("");
  const [manualBusy, setManualBusy] = useState(false);
  const status = criterion.verification_status ?? "pending";
  const cfg = STATUS_CONFIG[status];
  const isAutoApproved = status === "verified" && criterion.approved_by === "advisor";

  async function submitManual() {
    const text = manualText.trim();
    if (!text || manualBusy) return;
    setManualBusy(true);
    try {
      await mutate(
        `/api/specs/${spec.initiative_id}/criteria/${criterion.id}/evidence`,
        "POST",
        { evidence: text },
      );
      setManualOpen(false);
      setManualText("");
    } finally {
      setManualBusy(false);
    }
  }

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

  async function submitOverride() {
    if (!overrideFeedback.trim()) return;
    await mutate(
      `/api/specs/${spec.initiative_id}/criteria/${criterion.id}/verdict`,
      "POST",
      { verdict: "changes_requested", feedback: overrideFeedback.trim() },
    );
    setOverrideFeedback("");
    setShowOverride(false);
  }

  return (
    <>
      {/* Manual answer dialog */}
      <Dialog open={manualOpen} onOpenChange={setManualOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {status === "changes_requested"
                ? isResearch ? "Resubmit finding" : "Resubmit evidence"
                : isResearch ? "Submit finding" : "Submit evidence"}
            </DialogTitle>
          </DialogHeader>
          <div className="rounded-md border border-border bg-muted/30 px-3.5 py-3">
            <p className="text-[13.5px] leading-relaxed text-foreground">
              {criterion.text}
            </p>
            <div className="mt-2">
              <VerifyKindPill kind={criterion.verify?.kind} />
            </div>
          </div>
          <Textarea
            autoFocus
            rows={5}
            placeholder={
              isResearch
                ? "Describe what you found — literature reviewed, interview insights, data observed, etc."
                : "Describe the evidence — test output, metric reading, observed behavior, etc."
            }
            value={manualText}
            onChange={(e) => setManualText(e.target.value)}
            className="text-[13.5px]"
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setManualOpen(false)}>
              Cancel
            </Button>
            <Button disabled={!manualText.trim() || manualBusy} onClick={submitManual}>
              <Check className="size-3.5" />
              {status === "changes_requested"
                ? isResearch ? "Resubmit finding" : "Resubmit evidence"
                : isResearch ? "Submit finding" : "Submit evidence"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <li
        className={cn(
          "list-none rounded-lg border border-l-[3px] px-4 py-4",
          cfg.bar,
          cfg.card,
        )}
      >
        {/* Header row: status badge + action button */}
        <div className="flex items-start justify-between gap-3">
          <VerificationBadge status={status} isResearch={isResearch} />
          {status === "pending" && (
            <Button
              size="sm"
              variant="outline"
              className="h-6 shrink-0 px-2 text-[11px] text-ink-soft"
              onClick={() => setManualOpen(true)}
            >
              <PenLine className="size-3" />
              {isResearch ? "Answer" : "Submit"}
            </Button>
          )}
        </div>

        {/* Criterion text — the primary thing to read */}
        <p className="mt-2 text-[14.5px] leading-relaxed text-foreground">
          {criterion.text}
        </p>
        <div className="mt-2">
          <VerifyKindPill kind={criterion.verify?.kind} />
        </div>

        {/* Finding / evidence block */}
        {criterion.evidence && (
          <div className="mt-4 rounded-md border border-border bg-background/70 px-4 py-3">
            <p className="mb-1.5 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
              {isResearch ? "Finding" : "Evidence"}
            </p>
            <p className="text-[13.5px] leading-relaxed text-foreground">
              {criterion.evidence}
            </p>
          </div>
        )}

        {/* Feedback when changes requested */}
        {status === "changes_requested" && (
          <div className="mt-3 rounded-md border border-proposed/20 bg-proposed/[0.06] px-3.5 py-3">
            {criterion.feedback && (
              <>
                <p className="mb-1 font-mono text-[10px] tracking-widest text-proposed-foreground uppercase">
                  Feedback
                </p>
                <p className="text-[13px] leading-relaxed text-proposed-foreground">
                  {criterion.feedback}
                </p>
              </>
            )}
            <div className={criterion.feedback ? "mt-3" : ""}>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-[12px]"
                onClick={() => {
                  setManualText(criterion.evidence ?? "");
                  setManualOpen(true);
                }}
              >
                <PenLine className="size-3" />
                {isResearch ? "Resubmit finding" : "Resubmit evidence"}
              </Button>
            </div>
          </div>
        )}

        {/* BD-14: Advisor preliminary verdict */}
        {status === "evidence_submitted" && criterion.advisor_preliminary_verdict && (
          <div className="mt-4 rounded-md border border-border/60 bg-muted/40 px-3.5 py-3">
            <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] tracking-widest text-ink-faint uppercase">
              <Sparkles className="size-3" />
              <span>Advisor · preliminary</span>
              {criterion.advisor_preliminary_verdict === "pass" && (
                <span className="flex items-center gap-1 text-confirmed-foreground">
                  <Check className="size-3" /> pass
                </span>
              )}
              {criterion.advisor_preliminary_verdict === "borderline" && (
                <span className="flex items-center gap-1 text-amber-600">
                  <AlertTriangle className="size-3" /> borderline
                </span>
              )}
              {criterion.advisor_preliminary_verdict === "needs_your_eye" && (
                <span className="flex items-center gap-1 text-proposed-foreground">
                  <HelpCircle className="size-3" /> needs your eye
                </span>
              )}
            </div>
            {criterion.advisor_preliminary_notes && (
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {criterion.advisor_preliminary_notes}
              </p>
            )}
          </div>
        )}

        {/* Human verdict actions */}
        {status === "evidence_submitted" && (
          <div className="mt-4">
            {!showActions ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowActions(true)}
                className="h-7 text-[12px]"
              >
                {isResearch ? "Review finding" : "Review evidence"}
              </Button>
            ) : (
              <div className="space-y-3">
                <Textarea
                  rows={2}
                  placeholder={
                    isResearch
                      ? "What's missing or needs further investigation (required to request changes)"
                      : "Feedback (required to request changes)"
                  }
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  className="text-[13.5px]"
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={busy}
                    onClick={() => recordVerdict("approved")}
                    className="bg-confirmed text-white shadow-sm hover:bg-confirmed/90"
                  >
                    <Check /> {isResearch ? "Accept finding" : "Approve"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || !feedback.trim()}
                    title={!feedback.trim() ? "Add feedback first" : ""}
                    onClick={() => recordVerdict("changes_requested")}
                  >
                    <RotateCcw />{" "}
                    {isResearch ? "Needs more investigation" : "Request changes"}
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
          <div className="mt-3">
            {isAutoApproved ? (
              <div className="flex items-center justify-between gap-2">
                <p className="flex items-center gap-1.5 text-[13px] text-confirmed-foreground">
                  <Sparkles className="size-3.5" /> Auto-approved by Advisor
                </p>
                {!showOverride && (
                  <button
                    type="button"
                    onClick={() => setShowOverride(true)}
                    className="font-mono text-[10px] tracking-wide text-ink-faint underline-offset-4 hover:text-proposed-foreground hover:underline"
                  >
                    Override
                  </button>
                )}
              </div>
            ) : (
              <p className="flex items-center gap-1.5 text-[13px] text-confirmed-foreground">
                <Check className="size-3.5" /> Approved
                {criterion.feedback && (
                  <span className="text-ink-soft"> — {criterion.feedback}</span>
                )}
              </p>
            )}
            {showOverride && (
              <div className="mt-3 space-y-2.5">
                <Textarea
                  rows={2}
                  placeholder="Why the auto-approval is wrong (required)"
                  value={overrideFeedback}
                  onChange={(e) => setOverrideFeedback(e.target.value)}
                  className="text-[13.5px]"
                />
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || !overrideFeedback.trim()}
                    title={!overrideFeedback.trim() ? "Add feedback first" : ""}
                    onClick={submitOverride}
                  >
                    <RotateCcw /> Request changes
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-ink-faint"
                    onClick={() => {
                      setShowOverride(false);
                      setOverrideFeedback("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </li>
    </>
  );
}

export default function CriteriaVerification({
  initiativeId,
}: {
  initiativeId: string;
}) {
  const { spec, mutate, busy } = useSpec();
  const isResearch = spec.initiative_type === "research";
  const criteria = spec.acceptance;
  const isPostBuild = spec.state === "learning" || spec.state === "complete";
  const [collapsed, setCollapsed] = useState(isPostBuild);
  useEffect(() => {
    if (isPostBuild) setCollapsed(true);
  }, [isPostBuild]);

  if (criteria.length === 0) return null;

  const verified = criteria.filter((c) => c.verification_status === "verified").length;
  const withEvidence = criteria.filter(
    (c) =>
      c.verification_status === "evidence_submitted" ||
      c.verification_status === "verified",
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
          {isResearch ? "Findings" : "Verification"}
          <span className="font-normal tracking-normal text-ink-faint normal-case">
            · {isResearch ? "success criteria answered by findings" : "criteria verified by evidence"}
          </span>
        </button>

        <div className="flex items-center gap-3">
          {!allVerified && (
            <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-faint">
              {isResearch ? "agent should answer ·" : "agent should verify ·"}
              <button
                type="button"
                disabled={busy}
                onClick={approveAll}
                className="text-accent-deep underline-offset-4 hover:underline disabled:opacity-40"
              >
                approve all
              </button>
            </span>
          )}
          <span
            className={cn(
              "flex items-center gap-1.5 font-mono text-[10.5px] tabular-nums",
              allVerified ? "text-confirmed-foreground" : "text-ink-soft",
            )}
          >
            {allVerified && <Check className="size-3" />}
            {verified} / {criteria.length} {isResearch ? "answered" : "verified"}
          </span>
        </div>
      </div>

      {!collapsed && (
        <>
          {withEvidence === 0 && isResearch && (
            <p className="mt-3 text-[13px] text-ink-faint">
              No findings yet — submit findings from the conversation rail or answer criteria manually.
            </p>
          )}

          {withEvidence > 0 && (
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-border/70">
              <div
                className="h-full rounded-full bg-confirmed transition-all duration-500 ease-out"
                style={{ width: `${verifyPct}%` }}
              />
            </div>
          )}

          {/* BD-14: verification synthesis */}
          {spec.verification_synthesis &&
            criteria.some((c) => c.verification_status === "evidence_submitted") && (
              <div className="mt-4 rounded-lg border border-border bg-muted/40 px-4 py-3.5">
                <div className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-semibold tracking-widest text-ink-soft uppercase">
                  <Sparkles className="size-3" />
                  Advisor review
                </div>
                <p className="text-[13px] leading-relaxed text-foreground">
                  {spec.verification_synthesis}
                </p>
              </div>
            )}

          <ul className="mt-5 space-y-3">
            {criteria.map((c) => (
              <CriterionVerificationCard key={c.id} criterion={c} isResearch={isResearch} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
