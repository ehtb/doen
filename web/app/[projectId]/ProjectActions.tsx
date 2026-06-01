"use client";

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
  return (
    <section className="mt-24 border-t border-border pt-6">
      <p className="font-mono text-[10px] tracking-widest text-ink-faint uppercase">
        Manage project
      </p>

      <ArchiveProjectButton
        projectId={projectId}
        archived={archived}
        hasActiveInitiatives={hasActiveInitiatives}
      />
    </section>
  );
}
