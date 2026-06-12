"use client";

import useSWR from "swr";
import { Check, ClipboardCheck, GitBranch } from "lucide-react";
import { useSpec } from "./spec-context";
import { DECISIONS_SWR_KEY, decisionsFetcher } from "./AttentionSurface";
import { cn } from "@/lib/utils";
import type { Decision } from "@/lib/types";

export default function InitiativeStatus() {
  const { spec } = useSpec();
  const isResearch = spec.initiative_type === "research";
  const { data: decisions = [] } = useSWR<Decision[]>(
    DECISIONS_SWR_KEY(spec.initiative_id),
    decisionsFetcher,
    { refreshInterval: 3000, dedupingInterval: 2500, revalidateOnFocus: false },
  );

  const criteria = spec.acceptance;
  const verifiedCount = criteria.filter(
    (c) => c.verification_status === "verified",
  ).length;
  const showProgress =
    criteria.length > 0 &&
    (spec.state === "building" ||
      spec.state === "learning" ||
      spec.state === "complete");
  const verifyPct = criteria.length
    ? Math.round((verifiedCount / criteria.length) * 100)
    : 0;

  // Compute most urgent attention state
  const evidenceWaiting = criteria.filter(
    (c) => c.verification_status === "evidence_submitted",
  ).length;
  const decisionsWaiting = decisions.length;
  const proposedItems = [
    ...spec.constraints,
    ...spec.discretion,
    ...spec.acceptance,
  ].filter((i) => i.status === "proposed").length;

  return (
    <div className="mt-5 space-y-2">
      {/* Criteria verification progress bar */}
      {showProgress && (
        <div>
          <div className="flex items-center justify-between gap-3 mb-1.5">
            <span className="text-[13px] font-medium text-foreground">
              {isResearch ? "Findings progress" : "Criteria verification"}
            </span>
            <span
              className={cn(
                "text-[13px] font-semibold tabular-nums",
                verifiedCount === criteria.length
                  ? "text-confirmed-foreground"
                  : "text-confirmed-foreground",
              )}
            >
              {verifiedCount} / {criteria.length}{" "}
              {isResearch ? "answered" : "verified"}
            </span>
          </div>
          <div className="h-1 overflow-hidden rounded-sm bg-border/70">
            <div
              className="h-full rounded-sm bg-confirmed transition-all duration-300 ease-out"
              style={{ width: `${verifyPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Attention bar — single most urgent state */}
      {decisionsWaiting > 0 ? (
        <div className="flex items-center gap-2.5 rounded-lg border border-primary/30 bg-primary/[0.06] px-4 py-2.5">
          <GitBranch className="size-3.5 shrink-0 text-primary" />
          <span className="text-[13.5px] text-foreground">
            {decisionsWaiting} decision{decisionsWaiting === 1 ? "" : "s"}{" "}
            waiting on you
          </span>
        </div>
      ) : evidenceWaiting > 0 ? (
        <div
          className="flex items-center gap-2.5 rounded-lg px-4 py-2.5"
          style={{ background: "#F8F3E6", border: "1px solid #E8D99A" }}
        >
          <ClipboardCheck
            className="size-3.5 shrink-0"
            style={{ color: "#C4A24E" }}
          />
          <span className="text-[13.5px] text-foreground">
            {evidenceWaiting}{" "}
            {isResearch
              ? evidenceWaiting === 1
                ? "success criterion has findings"
                : "success criteria have findings"
              : evidenceWaiting === 1
                ? "criterion has evidence"
                : "criteria have evidence"}{" "}
            awaiting your review.
          </span>
        </div>
      ) : proposedItems > 0 ? (
        <div className="flex items-center gap-2.5 rounded-lg border border-border bg-card/60 px-4 py-2.5">
          <Check className="size-3.5 shrink-0 text-ink-faint" />
          <span className="text-[13.5px] text-foreground">
            {proposedItems} {proposedItems === 1 ? "item" : "items"} to confirm
          </span>
        </div>
      ) : null}
    </div>
  );
}
