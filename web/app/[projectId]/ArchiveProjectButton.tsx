"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Archive, ArchiveRestore, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { archiveProject, unarchiveProject } from "@/lib/api";

export default function ArchiveProjectButton({
  projectId,
  archived,
  hasActiveInitiatives,
}: {
  projectId: string;
  archived: boolean;
  hasActiveInitiatives: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doArchive() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setConfirming(false);
    try {
      await archiveProject(projectId);
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function doUnarchive() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await unarchiveProject(projectId);
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (archived) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={doUnarchive} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <ArchiveRestore />}
          Unarchive this project
        </Button>
        <span className="text-[12.5px] text-ink-faint">
          Restores the project to active status — all initiatives, specs, and history are intact.
        </span>
        {error && <span className="font-mono text-xs text-proposed-foreground">{error}</span>}
      </div>
    );
  }

  if (confirming) {
    return (
      <div className="animate-rise mt-3 rounded-md border border-proposed/30 bg-proposed/5 px-3.5 py-3">
        <p className="flex items-center gap-1.5 font-mono text-[11px] tracking-wide text-proposed-foreground uppercase">
          <AlertTriangle className="size-3.5" /> Confirm archive
        </p>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">
          {hasActiveInitiatives
            ? "This project has active initiatives. Archiving hides it from the project list — all specs, decisions, and history are preserved and the project remains accessible at its URL."
            : "Archiving hides this project from the project list — all specs, decisions, and history are preserved and the project remains accessible at its URL."}
        </p>
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Button variant="destructive" size="sm" disabled={busy} onClick={doArchive}>
            {busy ? <Loader2 className="animate-spin" /> : <Archive />} Yes, archive
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirming(false)}>
            Cancel
          </Button>
          {error && <span className="font-mono text-xs text-proposed-foreground">{error}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <Button
        variant="outline"
        size="sm"
        onClick={() => setConfirming(true)}
        disabled={busy}
      >
        {busy ? <Loader2 className="animate-spin" /> : <Archive />}
        Archive this project
      </Button>
      <span className="text-[12.5px] text-ink-faint">
        Hides the project from the active list — all specs and history are preserved.
      </span>
      {error && <span className="font-mono text-xs text-proposed-foreground">{error}</span>}
    </div>
  );
}
