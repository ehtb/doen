"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Archive, Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

// Reject (draft) and Archive (building/complete) share one mechanism in the backend; the UI
// just labels them according to the spec's current lifecycle (0013 follow-up). The action is
// destructive enough to merit an inline confirm — no surprise click-throughs.
export default function SpecActions({ projectId }: { projectId: string }) {
  const { spec } = useSpec();
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDraft = spec.state === "draft";
  const reason = isDraft ? "rejected" : "archived";
  const label = isDraft ? "Reject" : "Archive";
  const Icon = isDraft ? Trash2 : Archive;
  const explainer = isDraft
    ? "Rejects the draft — it disappears from the project. The spec stays on disk; you can revive it by URL."
    : "Archives this initiative — it disappears from the project. Its spec, work units, and memory are preserved.";

  async function act() {
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
      router.push(`/projects/${projectId}`);
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
      {!confirming ? (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => setConfirming(true)}>
            <Icon /> {label} this initiative
          </Button>
          <span className="text-[12.5px] text-ink-faint">{explainer}</span>
        </div>
      ) : (
        <div className="animate-rise mt-2 rounded-md border border-proposed/30 bg-proposed/5 px-3.5 py-3">
          <p className="flex items-center gap-1.5 font-mono text-[11px] tracking-wide text-proposed-foreground uppercase">
            <AlertTriangle className="size-3.5" /> Confirm {label.toLowerCase()}
          </p>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">{explainer}</p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button variant="destructive" size="sm" disabled={busy} onClick={act}>
              {busy ? <Loader2 className="animate-spin" /> : <Icon />} Yes, {label.toLowerCase()}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setConfirming(false)}
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
