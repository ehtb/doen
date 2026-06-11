import { notFound } from "next/navigation";
import { AlertTriangle, Archive, GitBranch, Layers } from "lucide-react";

import { getProjectDashboard } from "@/lib/api";
import { SetBreadcrumb } from "@/app/_shell/breadcrumb";
import NewInitiative from "../NewInitiative";
import CopySyncDocsPrompt from "./CopySyncDocsPrompt";
import OnboardingHint from "./OnboardingHint";
import ProjectIntent from "./ProjectIntent";
import ObservationsModal from "./ObservationsModal";
import WhatWeKnowModal from "./WhatWeKnowModal";
import { DashboardContent } from "./DashboardContent";
import ProjectActions from "./ProjectActions";

// The project as a whole — its grouped initiatives change live via client-side SWR in
// DashboardContent; no router.refresh() polling needed.
export const dynamic = "force-dynamic";

const ACTIVE_STATES = new Set(["draft", "building", "learning"]);

export default async function ProjectDashboardPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const data = await getProjectDashboard(projectId);
  if (!data) notFound();

  const { project, initiatives, open_decisions, pending_drift_reports, onboarding_prompt } = data;

  const activeCount = initiatives.filter((i) =>
    ACTIVE_STATES.has(i.state),
  ).length;
  const completedCount = initiatives.filter((i) => i.state === "complete").length;
  const hasActiveInitiatives = activeCount > 0;

  return (
    <main className="relative z-10 mx-auto max-w-[1180px] px-5 py-12 md:px-8">
      {/* the persistent header owns up-navigation now: Doen -> this project */}
      <SetBreadcrumb crumbs={[{ label: project.name }]} />

      <header className="animate-rise">
        {/* BD-11: archived banner — clearly visible, distinct from normal state */}
        {project.archived && (
          <div className="mb-5 flex items-center gap-2.5 rounded-lg border border-border bg-card/60 px-4 py-3">
            <Archive className="size-4 shrink-0 text-ink-faint" />
            <span className="font-mono text-[11.5px] text-muted-foreground">
              This project is archived. All initiatives and specs are intact.
              Use <span className="text-foreground">Manage project</span> below
              to unarchive.
            </span>
          </div>
        )}

        <span className="flex items-center gap-1.5 font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
          <Layers className="size-3.5" /> Project
        </span>
        <h1 className="mt-3 font-serif text-[clamp(2rem,5vw,3rem)] leading-[1.05] font-medium tracking-tight">
          {project.name}
        </h1>
        <ProjectIntent projectId={project.id} intent={project.intent} />

        {/* whole-project aggregate: active vs done split + open escalations */}
        <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border pt-3.5 font-mono text-[11px] text-ink-faint">
          <span>
            <span className="text-foreground">{activeCount}</span> active
          </span>
          <span>
            <span className="text-foreground">{completedCount}</span> done
          </span>
          <span className="flex items-center gap-1.5">
            <GitBranch className="size-3" />
            <span
              className={
                open_decisions > 0
                  ? "text-proposed-foreground"
                  : "text-foreground"
              }
            >
              {open_decisions}
            </span>{" "}
            open decision{open_decisions === 1 ? "" : "s"}
          </span>
          {pending_drift_reports > 0 && (
            <span className="flex items-center gap-1.5">
              <AlertTriangle className="size-3 text-accent-deep" />
              <span className="text-accent-deep">{pending_drift_reports}</span>{" "}
              drift report{pending_drift_reports === 1 ? "" : "s"}
            </span>
          )}
          {/* BD-14 u4: trigger a drift audit of core documentation from any project. */}
          <span className="ml-auto flex items-center gap-4">
            <ObservationsModal projectId={project.id} completedCount={completedCount} />
            <WhatWeKnowModal projectId={project.id} completedCount={completedCount} />
            <CopySyncDocsPrompt />
          </span>
        </div>
      </header>

      <div className="mt-9 grid grid-cols-1 gap-7 items-start md:grid-cols-[1fr_380px]">
        <section>
          {/* BD-9: onboarding hint — shown until dismissed, renders above initiatives so it
              does not affect the attention-priority sort order (constraint item_4c53a4c83230) */}
          <OnboardingHint
            projectId={project.id}
            prompt={onboarding_prompt}
            initialDismissed={project.onboarding_dismissed}
          />

          {/* BD-7: client-side SWR poll inside DashboardContent — no router.refresh() needed */}
          <DashboardContent projectId={projectId} initialData={data} />

          <ProjectActions
            projectId={project.id}
            archived={project.archived}
            hasActiveInitiatives={hasActiveInitiatives}
          />
        </section>

        {/* right column: shape form above, synthesis below */}
        <div className="flex flex-col gap-5 md:sticky md:top-6 md:self-start">
          <div className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-[18px] py-3.5">
              <span className="text-[13px] text-primary">✦</span>
              <span className="font-mono text-[10px] font-bold tracking-[0.1em] text-primary uppercase">New Initiative</span>
            </div>
            <div className="p-[18px]">
              <NewInitiative projectId={project.id} />
            </div>
          </div>

        </div>
      </div>
    </main>
  );
}
