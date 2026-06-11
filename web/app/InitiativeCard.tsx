import Link from "next/link";
import { ArrowRight, Loader2 } from "lucide-react";

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

// Single most-urgent attention line — prototype style: emoji + plain text, colored by urgency.
function AttentionLine({ attention, isResearch }: { attention: InitiativeAttention; isResearch: boolean }) {
  if (attention.is_shaping) {
    return (
      <span className="font-mono text-[11.5px] text-ink-faint">
        drafting spec…
      </span>
    );
  }
  if (attention.open_decisions > 0) {
    return (
      <span className="font-mono text-[12px] text-primary">
        ⚡ {attention.open_decisions} decision{attention.open_decisions === 1 ? "" : "s"} waiting
      </span>
    );
  }
  if ((attention.criteria_to_verify ?? 0) > 0) {
    return (
      <span className="font-mono text-[12px] text-confirmed-foreground">
        ✓ {attention.criteria_to_verify} {isResearch ? "findings to review" : "to verify"}
      </span>
    );
  }
  if ((attention.drift_reports ?? 0) > 0) {
    return (
      <span className="font-mono text-[12px] text-primary">
        ⚡ {attention.drift_reports} drift flagged
      </span>
    );
  }
  if (attention.proposed_items > 0) {
    return (
      <span className="font-mono text-[12px] text-confirmed-foreground">
        ✓ {attention.proposed_items} to confirm
      </span>
    );
  }
  return null;
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
  const isResearch = initiative.initiative_type === "research";
  const hasAttention = attention
    ? attention.proposed_items + attention.open_decisions + (attention.criteria_to_verify ?? 0) + (attention.drift_reports ?? 0) > 0 || attention.is_shaping
    : false;

  return (
    <Link
      href={href ?? `/${initiative.project_id}/${initiative.id}`}
      className="group block rounded-lg border border-border bg-card px-4 py-3 transition-colors hover:border-border/60 hover:bg-card/80"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14.5px] font-medium leading-snug text-foreground">
            {initiative.title ?? initiative.id}
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <span className="font-mono text-[10.5px] font-semibold tracking-wide text-primary">
              {shortId ?? initiative.id}
            </span>
            {/* BD-15: warm type tags matching prototype palette */}
            {isResearch ? (
              <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-widest uppercase bg-confirmed/15 text-confirmed-foreground">
                ◉ RES
              </span>
            ) : (
              <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-widest uppercase bg-primary/10 text-accent-deep">
                ⚙ ENG
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2.5 pt-0.5">
          <StateBadge state={initiative.state} />
          <ArrowRight className="size-3.5 text-ink-faint transition-transform group-hover:translate-x-0.5" />
        </div>
      </div>

      {attention && hasAttention && (
        <div className="mt-2">
          {attention.is_shaping ? (
            <span className="inline-flex items-center gap-1.5 font-mono text-[11.5px] text-ink-faint">
              <Loader2 className="size-3 animate-spin" /> drafting spec…
            </span>
          ) : (
            <AttentionLine attention={attention} isResearch={isResearch} />
          )}
        </div>
      )}
    </Link>
  );
}
