"use client";

import { useState } from "react";
import { AlertTriangle, Check, ExternalLink, Info, X } from "lucide-react";
import type { DriftReport, DriftReportQuality } from "@/lib/types";

async function resolveDriftReport(
  id: string,
  action: string,
  opts: { resolution_note?: string; memory_update?: { summary?: string; learnings?: string } } = {},
) {
  const res = await fetch(`/api/drift-reports/${id}/resolve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, ...opts }),
  });
  if (!res.ok) throw new Error(await res.text());
}

function QualityBadge({ quality }: { quality: DriftReportQuality }) {
  const [expanded, setExpanded] = useState(false);
  const pct = Math.round(quality.overall * 100);
  const color = quality.passed
    ? "text-confirmed-foreground bg-confirmed-foreground/10"
    : "text-accent-deep bg-primary/10";

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded((v) => !v)}
        className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] transition-colors ${color}`}
        title="LLM-as-judge quality evaluation"
      >
        <Info className="size-3" />
        evidence quality: {pct}% {quality.passed ? "✓" : "⚠"}
      </button>

      {expanded && (
        <div className="mt-2 rounded-md border border-border bg-background p-3 font-mono text-[10px] space-y-1.5">
          {quality.scores.map((s) => (
            <div key={s.name} className="flex items-start gap-2">
              <span className="w-20 shrink-0 text-ink-faint">{s.name}</span>
              <span className="w-4 shrink-0 font-semibold text-foreground">{s.score}/5</span>
              <span className="text-ink-soft">{s.reasoning}</span>
            </div>
          ))}
          {quality.warning && (
            <p className="mt-1.5 border-t border-border pt-1.5 text-accent-deep">
              {quality.warning}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ReportCard({
  report,
  onResolved,
  projectId,
}: {
  report: DriftReport;
  onResolved: () => void;
  projectId: string;
}) {
  const [loading, setLoading] = useState<string | null>(null);
  const [approveMode, setApproveMode] = useState(false);
  const [updatedSummary, setUpdatedSummary] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function act(action: string, opts = {}) {
    setLoading(action);
    setError(null);
    try {
      await resolveDriftReport(report.id, action, opts);
      onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setLoading(null);
    }
  }

  const filed = new Date(report.created_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });

  return (
    <div className="rounded-lg border border-border bg-card/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 font-mono text-[10px] text-ink-faint">
          <span className="font-semibold text-accent-deep">{report.memory_id}</span>
          {report.initiative_id && (
            <span>· from {report.initiative_id}</span>
          )}
          <span>· {filed}</span>
          {report.is_obsolete && (
            <span className="rounded-full bg-primary/15 px-1.5 py-0.5 text-accent-deep">
              obsolete
            </span>
          )}
        </div>
      </div>

      <p className="mt-2.5 text-sm leading-relaxed text-foreground">
        {report.current_evidence}
      </p>

      {report.quality && <QualityBadge quality={report.quality} />}

      {approveMode ? (
        <div className="mt-3 space-y-2">
          <label className="block font-mono text-[10px] text-ink-faint">
            Updated summary (leave blank to keep current)
          </label>
          <textarea
            value={updatedSummary}
            onChange={(e) => setUpdatedSummary(e.target.value)}
            rows={3}
            className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-foreground placeholder:text-ink-faint focus:border-accent-deep focus:outline-none"
            placeholder="Optional: paste corrected memory summary…"
          />
          <div className="flex gap-2">
            <button
              onClick={() =>
                act("approved", {
                  memory_update: updatedSummary.trim()
                    ? { summary: updatedSummary.trim() }
                    : undefined,
                  resolution_note: "Human approved memory update",
                })
              }
              disabled={!!loading}
              className="rounded-md bg-confirmed-foreground/15 px-3 py-1.5 font-mono text-[11px] text-confirmed-foreground transition-colors hover:bg-confirmed-foreground/25 disabled:opacity-50"
            >
              {loading === "approved" ? "Saving…" : "Confirm approve"}
            </button>
            <button
              onClick={() => setApproveMode(false)}
              disabled={!!loading}
              className="rounded-md border border-border px-3 py-1.5 font-mono text-[11px] text-ink-faint transition-colors hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => setApproveMode(true)}
            disabled={!!loading}
            className="flex items-center gap-1.5 rounded-md bg-confirmed-foreground/10 px-3 py-1.5 font-mono text-[11px] text-confirmed-foreground transition-colors hover:bg-confirmed-foreground/20 disabled:opacity-50"
          >
            <Check className="size-3" /> Approve update
          </button>
          <button
            onClick={() =>
              act("dismissed", { resolution_note: "Human dismissed as false alarm" })
            }
            disabled={!!loading}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 font-mono text-[11px] text-ink-faint transition-colors hover:text-foreground disabled:opacity-50"
          >
            <X className="size-3" /> {loading === "dismissed" ? "Dismissing…" : "Dismiss"}
          </button>
          <a
            href={`/${projectId}?new=1&description=${encodeURIComponent(
              `Fix drift in memory ${report.memory_id}: ${report.current_evidence.slice(0, 120)}`,
            )}`}
            onClick={() =>
              act("initiative_created", {
                resolution_note: "Human chose to create a new initiative to address the drift",
              })
            }
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 font-mono text-[11px] text-ink-faint transition-colors hover:text-foreground"
          >
            <ExternalLink className="size-3" /> Create initiative
          </a>
        </div>
      )}

      {error && (
        <p className="mt-2 font-mono text-[10px] text-destructive">{error}</p>
      )}
    </div>
  );
}

export function DriftReportsPanel({
  projectId,
  reports,
  onResolved,
}: {
  projectId: string;
  reports: DriftReport[];
  onResolved: () => void;
}) {
  if (reports.length === 0) return null;

  return (
    <div className="mt-5 rounded-lg border border-border bg-card/40">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <AlertTriangle className="size-3.5 shrink-0 text-accent-deep" />
        <span className="font-mono text-[11px] font-semibold text-accent-deep">
          {reports.length} drift report{reports.length === 1 ? "" : "s"} pending review
        </span>
        <span className="font-mono text-[10px] text-ink-faint">
          — memory entries an agent flagged as potentially outdated
        </span>
      </div>
      <div className="space-y-3 p-4">
        {reports.map((r) => (
          <ReportCard
            key={r.id}
            report={r}
            projectId={projectId}
            onResolved={onResolved}
          />
        ))}
      </div>
    </div>
  );
}
