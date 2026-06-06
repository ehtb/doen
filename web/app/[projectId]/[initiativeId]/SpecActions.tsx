"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Archive, Loader2, RefreshCw, RotateCcw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

// Reject (draft) and Archive (building/complete) share one mechanism in the backend; the UI
// just labels them according to the spec's current lifecycle (0013 follow-up). The action is
// destructive enough to merit an inline confirm — no surprise click-throughs.
export default function SpecActions({ projectId }: { projectId: string }) {
  const { spec, refreshSpec } = useSpec();
  const router = useRouter();
  const [confirming, setConfirming] = useState<"archive" | "revert" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDraft = spec.state === "draft";
  const isBuilding = spec.state === "building";
  const isShapingError = spec.shaping_status === "error";
  const reason = isDraft ? "rejected" : "archived";
  const label = isDraft ? "Reject" : "Archive";
  const Icon = isDraft ? Trash2 : Archive;
  const explainer = isDraft
    ? "Rejects the draft — it disappears from the project. The spec stays on disk; you can revive it by URL."
    : "Archives this initiative — it disappears from the project. Its spec, work units, and memory are preserved.";

  async function retryShaping() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/specs/${spec.initiative_id}/retry-shaping`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      });
      if (!res.ok) throw new Error(`retry failed (${res.status})`);
      // spec-context SWR will pick up the pending status and start showing spinners
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/initiatives/${spec.initiative_id}/archive`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) throw new Error(`${label.toLowerCase()} failed (${res.status})`);
      router.push(`/${projectId}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function revertToDraft() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/initiatives/${spec.initiative_id}/revert-to-draft`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      });
      if (!res.ok) throw new Error(`revert failed (${res.status})`);
      setConfirming(null);
      await refreshSpec();
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <section className="mt-12 border-t border-border pt-6">
      <p className="font-mono text-[10px] tracking-widest text-ink-faint uppercase">
        Manage initiative
      </p>

      {isShapingError && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" disabled={busy} onClick={retryShaping}>
            {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} Retry shaping
          </Button>
          <span className="text-[12.5px] text-ink-faint">
            The Advisor failed to draft this spec — retry to try again.
          </span>
          {error && (
            <span className="font-mono text-xs text-proposed-foreground">{error}</span>
          )}
        </div>
      )}

      {isBuilding && confirming !== "revert" && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => setConfirming("revert")}>
            <RotateCcw /> Move back to draft
          </Button>
          <span className="text-[12.5px] text-ink-faint">
            Unlocks the spec for editing — constraints, criteria, and agent latitude become
            editable again.
          </span>
        </div>
      )}

      {confirming === "revert" && (
        <div className="animate-rise mt-2 rounded-md border border-border bg-muted/40 px-3.5 py-3">
          <p className="flex items-center gap-1.5 font-mono text-[11px] tracking-wide text-ink-soft uppercase">
            <AlertTriangle className="size-3.5" /> Confirm revert to draft
          </p>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">
            The spec becomes editable again. Any submitted evidence stays as-is; the initiative
            will return to building once evidence is submitted again.
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={busy} onClick={revertToDraft}>
              {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />} Yes, revert to draft
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setConfirming(null)}
            >
              Cancel
            </Button>
            {error && (
              <span className="font-mono text-xs text-proposed-foreground">{error}</span>
            )}
          </div>
        </div>
      )}

      {confirming !== "archive" ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => setConfirming("archive")}>
            <Icon /> {label} this initiative
          </Button>
          <span className="text-[12.5px] text-ink-faint">{explainer}</span>
        </div>
      ) : (
        <div className="animate-rise mt-3 rounded-md border border-proposed/30 bg-proposed/5 px-3.5 py-3">
          <p className="flex items-center gap-1.5 font-mono text-[11px] tracking-wide text-proposed-foreground uppercase">
            <AlertTriangle className="size-3.5" /> Confirm {label.toLowerCase()}
          </p>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">{explainer}</p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button variant="destructive" size="sm" disabled={busy} onClick={archive}>
              {busy ? <Loader2 className="animate-spin" /> : <Icon />} Yes, {label.toLowerCase()}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setConfirming(null)}
            >
              Cancel
            </Button>
            {error && (
              <span className="font-mono text-xs text-proposed-foreground">{error}</span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
