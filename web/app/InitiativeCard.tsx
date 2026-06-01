import Link from "next/link";
import { ArrowRight } from "lucide-react";

import type { Initiative } from "@/lib/types";

export const STAGES = [
  "discover",
  "shape",
  "bet",
  "decompose",
  "implement",
  "verify",
  "learn",
];

export function StageBadge({ stage }: { stage: string }) {
  const i = STAGES.indexOf(stage);
  const pos = i < 0 ? "" : `${i + 1}/${STAGES.length}`;
  return (
    <span className="flex shrink-0 items-center gap-1.5 font-mono text-[10px] tracking-widest text-accent-deep uppercase">
      <span className="size-1.5 rounded-full bg-primary" />
      {stage}
      {pos && <span className="text-ink-faint normal-case">· {pos}</span>}
    </span>
  );
}

// One initiative on a feed — the home dashboard and the project dashboard render the same
// card, linking into the initiative's living spec.
export function InitiativeCard({ initiative }: { initiative: Initiative }) {
  return (
    <Link
      href={`/projects/${initiative.project_id}/specs/${initiative.id}`}
      className="group block rounded-lg border border-border bg-card/60 px-5 py-4 transition-colors hover:bg-card"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate font-serif text-[19px] leading-snug">
            {initiative.title ?? initiative.id}
          </h3>
          <p className="mt-1 font-mono text-[11px] text-ink-faint">{initiative.id}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <StageBadge stage={initiative.stage} />
          <ArrowRight className="size-4 text-ink-faint transition-transform group-hover:translate-x-0.5" />
        </div>
      </div>
    </Link>
  );
}
