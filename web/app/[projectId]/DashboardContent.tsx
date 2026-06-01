"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { Search, CheckCircle2, ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import useSWR from "swr";

import { shortId } from "@/lib/utils";
import { InitiativeCard } from "../InitiativeCard";
import type { Initiative, InitiativeAttention, Project, ProjectDashboard } from "@/lib/types";

// Attention priority tiers (BD-7 constraint 2):
// 1 = decisions to resolve (blocking the agent)
// 2 = criteria to verify (evidence submitted, waiting for human judgment)
// 3 = items to confirm (spec being shaped)
// 4 = in-progress unblocked (agent is working)
// 5 = untouched draft (created but not yet shaped)
function attentionTier(
  attention: InitiativeAttention | undefined,
  state: string,
): number {
  if ((attention?.open_decisions ?? 0) > 0) return 1;
  if ((attention?.criteria_to_verify ?? 0) > 0) return 2;
  if ((attention?.proposed_items ?? 0) > 0) return 3;
  if (state === "draft") return 5;
  return 4;
}

function matchesSearch(initiative: Initiative, sId: string, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return sId.toLowerCase().includes(q) || (initiative.title ?? "").toLowerCase().includes(q);
}

function formatCompletionDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function CompletedRow({
  initiative,
  sId,
  linkHref,
}: {
  initiative: Initiative;
  sId: string;
  linkHref: string;
}) {
  return (
    <li>
      <Link
        href={linkHref}
        className="group flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-card/60"
      >
        <span className="w-14 shrink-0 font-mono text-[10px] font-semibold tracking-wide text-accent-deep">
          {sId}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-foreground">
          {initiative.title ?? initiative.id}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-ink-faint">
          {formatCompletionDate(initiative.updated_at)}
        </span>
        <ArrowRight className="size-3.5 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </Link>
    </li>
  );
}

const ACTIVE_STATES = new Set(["draft", "building", "learning"]);

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function DashboardContent({
  projectId,
  initialData,
}: {
  projectId: string;
  initialData: ProjectDashboard;
}) {
  const { data } = useSWR<ProjectDashboard>(
    `/api/projects/${projectId}/dashboard`,
    fetcher,
    { fallbackData: initialData, refreshInterval: 5000, revalidateOnFocus: false, dedupingInterval: 4000 },
  );
  const { initiatives, attention, project } = data!;
  const [search, setSearch] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);

  const sId = (i: Initiative) => shortId(project.prefix, i.seq);
  const href = (i: Initiative) => `/${project.id}/${i.id}`;

  const active = useMemo(
    () =>
      initiatives
        .filter((i) => ACTIVE_STATES.has(i.state))
        .sort(
          (a, b) =>
            attentionTier(attention[a.id], a.state) -
            attentionTier(attention[b.id], b.state),
        ),
    [initiatives, attention],
  );

  const completed = useMemo(
    () => initiatives.filter((i) => i.state === "complete"),
    [initiatives],
  );

  const query = search.trim().toLowerCase();

  const filteredActive = query
    ? active.filter((i) => matchesSearch(i, sId(i), query))
    : active;

  const filteredCompleted = query
    ? completed.filter((i) => matchesSearch(i, sId(i), query))
    : completed;

  // "Nothing waiting" is shown when all active initiatives are in tier 4/5 (no human action needed).
  const nothingWaiting =
    !query &&
    active.length > 0 &&
    active.every((i) => attentionTier(attention[i.id], i.state) >= 4);

  return (
    <>
      {/* Search */}
      <div className="relative mt-4">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-ink-faint" />
        <input
          type="search"
          placeholder="Find by title or ID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-md border border-border bg-background py-2 pl-8 pr-3 font-mono text-[12px] placeholder:text-ink-faint focus:border-accent-deep focus:outline-none focus:ring-0"
        />
      </div>

      {/* Nothing waiting banner */}
      {nothingWaiting && (
        <div className="mt-5 flex items-center gap-2 rounded-lg border border-border bg-card/40 px-4 py-3">
          <CheckCircle2 className="size-4 shrink-0 text-confirmed-foreground" />
          <span className="font-mono text-[11px] text-ink-soft">
            Nothing waiting for you — the agent is working.{" "}
            <span className="text-ink-faint">
              Shape a new initiative or ask the Advisor what to build next.
            </span>
          </span>
        </div>
      )}

      {/* Active initiatives */}
      {filteredActive.length > 0 ? (
        <ul className="mt-5 space-y-2.5">
          {filteredActive.map((i) => (
            <li key={i.id}>
              <InitiativeCard
                initiative={i}
                attention={attention[i.id]}
                shortId={sId(i)}
                href={href(i)}
              />
            </li>
          ))}
        </ul>
      ) : active.length === 0 && !query ? (
        <p className="mt-5 text-sm text-muted-foreground">
          No active initiatives — describe one above and the Advisor shapes it.
        </p>
      ) : null}

      {/* Completed section — toggle when not searching; auto-expanded when search has matches */}
      {!query && completed.length > 0 && (
        <div className="mt-7">
          <button
            onClick={() => setShowCompleted((v) => !v)}
            className="flex items-center gap-2 font-mono text-[11px] text-ink-faint transition-colors hover:text-ink-soft"
          >
            {showCompleted ? (
              <ChevronUp className="size-3.5" />
            ) : (
              <ChevronDown className="size-3.5" />
            )}
            {showCompleted ? "Hide" : "Show"} {completed.length} completed
          </button>

          {showCompleted && (
            <ul className="mt-2 divide-y divide-border rounded-md border border-border">
              {completed.map((i) => (
                <CompletedRow key={i.id} initiative={i} sId={sId(i)} linkHref={href(i)} />
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Searching: show completed matches below active results */}
      {query && filteredCompleted.length > 0 && (
        <div className="mt-7">
          <p className="mb-2 font-mono text-[11px] tracking-widest text-ink-faint uppercase">
            Completed
          </p>
          <ul className="divide-y divide-border rounded-md border border-border">
            {filteredCompleted.map((i) => (
              <CompletedRow key={i.id} initiative={i} sId={sId(i)} linkHref={href(i)} />
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
