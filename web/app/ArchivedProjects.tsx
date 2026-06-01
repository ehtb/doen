"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronDown, ChevronUp, Layers } from "lucide-react";

import type { Project } from "@/lib/types";

function ArchivedProjectRow({ project, count }: { project: Project; count: number }) {
  return (
    <li>
      <Link
        href={`/${project.id}`}
        className="group flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-card/60"
      >
        <Layers className="size-3.5 shrink-0 text-ink-faint" />
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
          {project.name}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-ink-faint">
          {count} initiative{count === 1 ? "" : "s"}
        </span>
        <ArrowRight className="size-3.5 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </Link>
    </li>
  );
}

export default function ArchivedProjects({
  projects,
  counts,
}: {
  projects: Project[];
  counts: Record<string, number>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <section className="animate-rise mt-10 [animation-delay:120ms]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 font-mono text-[11px] text-ink-faint transition-colors hover:text-ink-soft"
      >
        {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        {open ? "Hide" : "Show"} {projects.length} archived project
        {projects.length === 1 ? "" : "s"}
      </button>

      {open && (
        <ul className="mt-2 divide-y divide-border rounded-md border border-border">
          {projects.map((p) => (
            <ArchivedProjectRow key={p.id} project={p} count={counts[p.id] ?? 0} />
          ))}
        </ul>
      )}
    </section>
  );
}
