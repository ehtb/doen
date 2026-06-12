"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, Check, ClipboardCheck, Copy, FlaskConical, Loader2, MessageSquare, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

function buildMcpPrompt(initiativeId: string, title: string) {
  return `Build initiative ${initiativeId} — ${title}.

Call get_spec("${initiativeId}") and get_conversation_summary("${initiativeId}") to ground yourself in the spec and its resolved decisions. Then follow the spec-contract: claim units, build against confirmed items only, escalate decisions with raise_decision, submit_for_verification when done.`;
}

function buildPlanPrompt(initiativeId: string, title: string) {
  return `Plan the build for initiative ${initiativeId} — ${title}.

Call get_spec("${initiativeId}") and get_conversation_summary("${initiativeId}") to ground yourself in the spec and its resolved decisions. Lay out a step-by-step build plan — one step per work unit — covering what you'll build, in what order, and which decisions you might need to raise. Do NOT start building yet. Present the plan for review first. When approved follow the spec-contract: claim units, build against confirmed items only, escalate decisions with raise_decision, submit_for_verification when done.`;
}

const BASE = "animate-rise mt-5 flex flex-wrap items-center gap-4 rounded-xl border px-4 py-3.5";
const IDLE = `${BASE} border-border bg-card/60`;
const ACTIVE = `${BASE} border-primary/30 bg-primary/[0.04]`;
const DONE = `${BASE} border-confirmed/30 bg-confirmed/[0.04]`;

export default function NextStepHint() {
  const { spec, refreshSpec } = useSpec();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [copiedKey, setCopiedKey] = useState<"execute" | "plan" | null>(null);

  const isResearch = spec.initiative_type === "research";
  const executePrompt = buildMcpPrompt(spec.initiative_id, spec.title);
  const planPrompt = buildPlanPrompt(spec.initiative_id, spec.title);

  const items = [...spec.constraints, ...spec.discretion, ...spec.acceptance];
  const reviewable = items.filter((i) => i.status !== "retired");
  const confirmedCount = reviewable.filter((i) => i.status === "confirmed").length;
  const proposedCount = reviewable.filter((i) => i.status === "proposed").length;
  const fullyReviewed =
    reviewable.length > 0 && proposedCount === 0 && confirmedCount > 0;

  async function startBuilding() {
    if (busy) return;
    setBusy(true);
    try {
      await fetch(`/api/initiatives/${spec.initiative_id}/start-building`, { method: "POST" });
      await refreshSpec();
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function copyPrompt(key: "execute" | "plan") {
    await navigator.clipboard.writeText(key === "execute" ? executePrompt : planPrompt);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  }

  // ── complete ──────────────────────────────────────────────────────────────
  if (spec.state === "complete") return null;

  // ── learning: all criteria verified, retrospective next ──────────────────
  if (spec.state === "learning") {
    return (
      <div className={DONE}>
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10.5px] font-semibold tracking-widest text-confirmed-foreground uppercase">
            {isResearch ? "All findings verified" : "All criteria verified"}
          </p>
          <p className="text-[13.5px] leading-relaxed text-foreground">
            {isResearch
              ? "Write the conclusion and retrospective below to close the investigation and feed its learnings back to the flywheel."
              : "Write the retrospective below to close this initiative and feed its learnings back to the flywheel."}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="shadow-sm shrink-0"
          onClick={() => document.getElementById("learn")?.scrollIntoView({ behavior: "smooth" })}
        >
          <ArrowDown className="size-3.5" /> {isResearch ? "Write conclusion" : "Write retrospective"}
        </Button>
      </div>
    );
  }

  // ── building ──────────────────────────────────────────────────────────────
  if (spec.state === "building") {
    const evidenceSubmitted = spec.acceptance.some(
      (c) => c.verification_status === "evidence_submitted",
    );

    // findings/evidence waiting → review is the next human action
    if (evidenceSubmitted) {
      return (
        <div className={ACTIVE}>
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[10.5px] font-semibold tracking-widest text-accent-deep uppercase">
              {isResearch ? "Findings awaiting review" : "Evidence awaiting review"}
            </p>
            <p className="text-[13.5px] leading-relaxed text-foreground">
              {isResearch
                ? "Findings have been submitted against a success criterion. Review them and approve or request more investigation before continuing."
                : "The executor submitted evidence against a criterion. Review it and approve or request changes before the next build step."}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="shadow-sm shrink-0"
            onClick={() =>
              document.getElementById("criteria-verification")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            <ClipboardCheck className="size-3.5" />
            {isResearch ? "Review findings" : "Review evidence"}
          </Button>
        </div>
      );
    }

    // research: investigation is underway via the Advisor rail
    if (isResearch) {
      return (
        <div className={ACTIVE}>
          <FlaskConical className="size-4 shrink-0 text-accent-deep" />
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[10.5px] font-semibold tracking-widest text-accent-deep uppercase">
              Investigating
            </p>
            <p className="text-[13.5px] leading-relaxed text-foreground">
              Talk to the Advisor in the rail — share what you're finding, ask it to surface contradictions, and check whether findings satisfy criteria. When a finding is strong enough, submit it from the conversation.
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="shadow-sm shrink-0"
            onClick={() => document.querySelector("textarea")?.focus()}
          >
            <MessageSquare className="size-3.5" /> Open Advisor
          </Button>
        </div>
      );
    }

    // engineering: give the prompt to Claude Code
    return (
      <div className={ACTIVE}>
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10.5px] font-semibold tracking-widest text-accent-deep uppercase">
            Give this to Claude Code
          </p>
          <p className="text-[13.5px] leading-relaxed text-foreground">
            Paste the MCP prompt into Claude Code (or any MCP-connected executor) to start building against the confirmed spec.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button size="sm" variant="outline" onClick={() => copyPrompt("plan")} className="shadow-sm">
            {copiedKey === "plan" ? <><Check className="size-3.5" /> Copied</> : <><Copy className="size-3.5" /> Plan first</>}
          </Button>
          <Button size="sm" variant="outline" onClick={() => copyPrompt("execute")} className="shadow-sm">
            {copiedKey === "execute" ? <><Check className="size-3.5" /> Copied</> : <><Copy className="size-3.5" /> Execute</>}
          </Button>
        </div>
      </div>
    );
  }

  // ── draft ─────────────────────────────────────────────────────────────────

  // shaping in progress — spec items not yet available
  if (spec.shaping_status === "pending") {
    return (
      <div className={IDLE}>
        <Loader2 className="size-4 shrink-0 animate-spin text-ink-faint" />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10.5px] font-semibold tracking-widest text-ink-soft uppercase">
            Drafting your spec
          </p>
          <p className="text-[13.5px] leading-relaxed text-foreground">
            The Advisor is shaping your description into constraints, {isResearch ? "success criteria" : "acceptance criteria"}, and {isResearch ? "investigator" : "agent"} latitude. It'll be ready to review shortly.
          </p>
        </div>
      </div>
    );
  }

  // items exist but not all reviewed — guide to the review step
  if (reviewable.length > 0 && proposedCount > 0) {
    return (
      <div className={IDLE}>
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10.5px] font-semibold tracking-widest text-ink-soft uppercase">
            Review the spec
          </p>
          <p className="text-[13.5px] leading-relaxed text-foreground">
            Accept or reject each proposed item in the Advisor rail.{" "}
            <span className="text-ink-faint">
              {confirmedCount} of {reviewable.length} confirmed{proposedCount > 0 ? `, ${proposedCount} to go` : ""}.
            </span>
          </p>
        </div>
        <span className="shrink-0 font-mono text-[11px] tabular-nums text-ink-faint">
          step 1 of {isResearch ? "3" : "3"}
        </span>
      </div>
    );
  }

  // fully reviewed — prompt to start
  if (fullyReviewed) {
    return (
      <div className={ACTIVE}>
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10.5px] font-semibold tracking-widest text-accent-deep uppercase">
            {isResearch ? "Ready to investigate" : "Ready to build"}
          </p>
          <p className="text-[13.5px] leading-relaxed text-foreground">
            {isResearch
              ? "Spec is confirmed. Start the investigation — the Advisor will switch to investigation mode. The initiative also transitions automatically when you submit your first finding."
              : "Spec is confirmed. Start the build — or give the MCP prompt to Claude Code and it will transition automatically when it submits the first piece of evidence."}
          </p>
        </div>
        <Button size="sm" disabled={busy} onClick={startBuilding} className="shadow-sm shrink-0">
          {busy ? <Loader2 className="animate-spin" /> : <Sparkles className="size-3.5" />}
          {isResearch ? "Start investigating" : "Start building"}
        </Button>
      </div>
    );
  }

  // empty spec (no items shaped yet, no shaping in progress) — nothing useful to show
  return null;
}
