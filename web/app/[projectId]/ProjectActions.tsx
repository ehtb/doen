"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Settings } from "lucide-react";
import ArchiveProjectButton from "./ArchiveProjectButton";

export default function ProjectActions({
  projectId,
  archived,
  hasActiveInitiatives,
}: {
  projectId: string;
  archived: boolean;
  hasActiveInitiatives: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <section className="mt-24 border-t border-border pt-6">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 rounded-md py-1 text-left transition-colors hover:text-foreground"
      >
        <span className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          <Settings className="size-3.5" />
          Manage project
        </span>
      </button>

      {open && (
        <div className="mt-2">
          <ArchiveProjectButton
            projectId={projectId}
            archived={archived}
            hasActiveInitiatives={hasActiveInitiatives}
          />
        </div>
      )}
    </section>
  );
}
