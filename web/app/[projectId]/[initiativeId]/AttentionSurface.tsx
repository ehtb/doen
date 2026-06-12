"use client";

import { type ReactNode } from "react";
import useSWR from "swr";
import { ArrowDownRight, Check, GitBranch, X } from "lucide-react";

import type { Decision, Spec, SpecItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// The spec page leads with what needs YOU (0011 C4/a5): a pinned surface above the full spec.
// Priority is decisions > verifications > confirmations (the author's ranking — a blocked agent
// outranks a proposal awaiting review). Decisions are fetched via SWR (shared key with
// SteeringRail — one request serves both); proposed spec items come from the spec the parent owns,
// so accept/reject stays consistent with the document below and the count updates live (a5).

const DECISIONS_SWR_KEY = (id: string) => `/api/initiatives/${id}/decisions`;
const decisionsFetcher = (url: string) =>
  fetch(url, { cache: "no-store" }).then((r) => (r.ok ? r.json() : []));

type Section = "constraints" | "discretion" | "acceptance";
const SECTIONS: Section[] = ["constraints", "discretion", "acceptance"];
const ITEM_LABEL: Record<Section, string> = {
  constraints: "constraint",
  discretion: "discretion",
  acceptance: "criterion",
};

export { DECISIONS_SWR_KEY, decisionsFetcher };

export default function AttentionSurface({
  spec,
  initiativeId,
  onConfirmItem,
  onRejectItem,
  busy,
}: {
  spec: Spec;
  initiativeId: string;
  onConfirmItem: (it: SpecItem) => void;
  onRejectItem: (it: SpecItem) => void;
  busy: boolean;
}) {
  const { data: decisions = [] } = useSWR<Decision[]>(
    DECISIONS_SWR_KEY(initiativeId),
    decisionsFetcher,
    { refreshInterval: 3000, dedupingInterval: 2500, revalidateOnFocus: false },
  );

  const proposedItems: { section: Section; it: SpecItem }[] = SECTIONS.flatMap((s) =>
    (spec[s] as SpecItem[]).filter((i) => i.status === "proposed").map((it) => ({ section: s, it })),
  );
  const total = decisions.length + proposedItems.length;

  const isResearch = spec.initiative_type === "research";
  const labelFor = (section: Section) => {
    if (section === "acceptance") return isResearch ? "success criterion" : "criterion";
    return ITEM_LABEL[section];
  };

  if (total === 0) {
    return (
      <section className="rounded-xl border border-confirmed/30 bg-confirmed/[0.05] px-5 py-4">
        <p className="flex items-center gap-2 font-mono text-[11.5px] tracking-wide text-confirmed-foreground">
          <Check className="size-3.5" /> Nothing needs you right now — the spec below is the record.
        </p>
      </section>
    );
  }

  return (
    <section className="animate-rise rounded-xl border border-primary/30 bg-primary/[0.04] p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.14em] text-accent-deep uppercase">
          Needs your attention
        </h2>
        <span className="flex size-6 items-center justify-center rounded-full bg-primary font-mono text-[11px] font-semibold text-white tabular-nums">
          {total}
        </span>
      </div>

      <div className="mt-3.5 space-y-2">
        {/* 1 — open decisions: a blocked agent is the most urgent thing on the page */}
        {decisions.map((d) => (
          <Row key={d.id} tone="urgent" tag="decision" icon={<GitBranch className="size-3" />}>
            <p className="text-[13px] leading-snug text-foreground">{d.question}</p>
            <a
              href="#steering-rail"
              className="mt-1 inline-flex items-center gap-1 font-mono text-[10.5px] tracking-wide text-accent-deep hover:underline"
            >
              resolve on the steering rail <ArrowDownRight className="size-3" />
            </a>
          </Row>
        ))}

        {/* 2 — awaiting confirmation: proposed spec items, with inline accept/reject */}
        {proposedItems.map(({ section, it }) => (
          <Row key={it.id} tone="pending" tag={labelFor(section)}>
            <p className="font-mono text-[12.5px] leading-snug text-foreground">{it.text}</p>
            <AcceptReject
              busy={busy}
              onAccept={() => onConfirmItem(it)}
              onReject={() => onRejectItem(it)}
            />
          </Row>
        ))}

      </div>
    </section>
  );
}

function Row({
  tone,
  tag,
  icon,
  children,
}: {
  tone: "urgent" | "pending";
  tag: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-l-[3px] bg-card/70 px-3.5 py-2.5",
        tone === "urgent" ? "border-l-primary" : "border-l-proposed",
      )}
    >
      <div
        className={cn(
          "mb-1 flex items-center gap-1.5 font-mono text-[10px] tracking-widest uppercase",
          tone === "urgent" ? "text-accent-deep" : "text-proposed-foreground",
        )}
      >
        {icon}
        {tag}
      </div>
      {children}
    </div>
  );
}

function AcceptReject({
  busy,
  onAccept,
  onReject,
}: {
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  return (
    <div className="mt-2 flex gap-2">
      <Button
        size="sm"
        disabled={busy}
        onClick={onAccept}
        className="h-7 bg-confirmed px-2.5 text-white shadow-sm hover:bg-confirmed/90"
      >
        <Check /> Accept
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={onReject}
        className="h-7 px-2.5 text-proposed-foreground hover:bg-proposed/10"
      >
        <X /> Reject
      </Button>
    </div>
  );
}
