import Link from "next/link";
import { ArrowRight, Check, GitBranch, ClipboardCheck, AlertTriangle, FlaskConical, Wrench } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Initiative, InitiativeAttention } from "@/lib/types";

// Active states (draft/building/learning) + terminal state (complete). BD-7: learning is active.
export const STATES = ["draft", "building", "learning", "complete"];

const STATE_STYLE: Record<string, string> = {
  draft: "text-ink-soft",
  building: "text-accent-deep",
  learning: "text-accent-deep",
  complete: "text-confirmed-foreground",
};

export function StateBadge({ state }: { state: string }) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center gap-1.5 font-mono text-[10px] tracking-widest uppercase",
        STATE_STYLE[state] ?? "text-ink-faint",
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {state}
    </span>
  );
}

// A small "needs you" chip — only shown when its count is non-zero (0011 a8).
function AttentionChip({
  icon: Icon,
  n,
  label,
  urgent,
}: {
  icon: typeof Check;
  n: number;
  label: string;
  urgent?: boolean;
}) {
  if (n <= 0) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] tracking-wide",
        urgent
          ? "bg-primary/15 text-accent-deep"
          : "bg-proposed/15 text-proposed-foreground",
      )}
      title={`${n} ${label}`}
    >
      <Icon className="size-3" />
      {n} {label}
    </span>
  );
}

// One initiative on a feed — the home dashboard and the project dashboard render the same
// card, linking into the initiative's living spec. On the project screen it also carries
// attention indicators (0011 a8): what needs the human, visible without opening the spec.
export function InitiativeCard({
  initiative,
  attention,
  shortId,
  href,
}: {
  initiative: Initiative;
  attention?: InitiativeAttention;
  // 0012 u5/a11: when the parent knows the project prefix it passes the short id (BD-7) + the
  // short-slug href; on feeds that don't (the cross-project home), we fall back to the long id
  // (which still resolves and redirects).
  shortId?: string;
  href?: string;
}) {
  const total = attention
    ? attention.proposed_items +
      attention.open_decisions +
      (attention.criteria_to_verify ?? 0) +
      (attention.drift_reports ?? 0)
    : 0;
  return (
    <Link
      href={href ?? `/${initiative.project_id}/${initiative.id}`}
      className="group block rounded-lg border border-border bg-card/60 px-5 py-4 transition-colors hover:bg-card"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate font-serif text-[19px] leading-snug">
            {initiative.title ?? initiative.id}
          </h3>
          <div className="mt-1 flex items-center gap-2">
            <p className="font-mono text-[11px] text-ink-faint">
              {shortId ? (
                <span className="font-semibold tracking-wide text-accent-deep">{shortId}</span>
              ) : (
                initiative.id
              )}
            </p>
            {/* BD-15: type indicator — distinguishable at a glance */}
            {initiative.initiative_type === "research" ? (
              <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[9px] tracking-widest uppercase bg-violet-50 text-violet-600 dark:bg-violet-950/40 dark:text-violet-400">
                <FlaskConical className="size-2.5" /> research
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[9px] tracking-widest uppercase bg-sky-50 text-sky-600 dark:bg-sky-950/40 dark:text-sky-400">
                <Wrench className="size-2.5" /> engineering
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <StateBadge state={initiative.state} />
          <ArrowRight className="size-4 text-ink-faint transition-transform group-hover:translate-x-0.5" />
        </div>
      </div>

      {attention && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {total === 0 ? (
            <span className="inline-flex items-center gap-1 font-mono text-[10px] tracking-wide text-ink-faint">
              <Check className="size-3" /> nothing waiting
            </span>
          ) : (
            <>
              <AttentionChip
                icon={GitBranch}
                n={attention.open_decisions}
                label="to decide"
                urgent
              />
              <AttentionChip
                icon={ClipboardCheck}
                n={attention.criteria_to_verify ?? 0}
                // BD-15: adapt label per type
                label={initiative.initiative_type === "research" ? "findings to review" : "to verify"}
                urgent
              />
              <AttentionChip
                icon={AlertTriangle}
                n={attention.drift_reports ?? 0}
                label="drift flagged"
                urgent
              />
              <AttentionChip icon={Check} n={attention.proposed_items} label="to confirm" />
            </>
          )}
        </div>
      )}
    </Link>
  );
}
