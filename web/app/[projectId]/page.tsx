import { notFound } from "next/navigation";
import { AlertTriangle, Archive, GitBranch, Layers } from "lucide-react";

import { getProjectDashboard } from "@/lib/api";
import { SetBreadcrumb } from "@/app/_shell/breadcrumb";
import NewInitiative from "../NewInitiative";
import CopySyncDocsPrompt from "./CopySyncDocsPrompt";
import OnboardingHint from "./OnboardingHint";
import ProjectIntent from "./ProjectIntent";
import ProjectSynthesis from "./ProjectSynthesis";
import ConversationRail from "@/app/[projectId]/[initiativeId]/ConversationRail";
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
          <span className="ml-auto">
            <CopySyncDocsPrompt />
          </span>
        </div>
      </header>

      <div className="mt-9 flex flex-wrap items-start gap-7">
        <section className="min-w-80 flex-[1_1_520px]">
          {/* BD-9: onboarding hint — shown until dismissed, renders above initiatives so it
              does not affect the attention-priority sort order (constraint item_4c53a4c83230) */}
          <OnboardingHint
            projectId={project.id}
            prompt={onboarding_prompt}
            initialDismissed={project.onboarding_dismissed}
          />

          {/* BD-20: proactive advisor observations + 'what we know' synthesis. Non-intrusive
              and dismissible; loaded client-side so the page renders without waiting on the LLM. */}
          <ProjectSynthesis
            projectId={project.id}
            completedCount={completedCount}
          />

          <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
            Initiatives
            <span className="font-normal tracking-normal text-ink-faint normal-case">
              · {initiatives.length}
            </span>
          </h2>

          {/* BD-7: client-side SWR poll inside DashboardContent — no router.refresh() needed */}
          <DashboardContent projectId={projectId} initialData={data} />

          <ProjectActions
            projectId={project.id}
            archived={project.archived}
            hasActiveInitiatives={hasActiveInitiatives}
          />
        </section>

        {/* right column: shape form above, Advisor below */}
        <div className="sticky top-6 min-w-80 flex-[1_1_360px] self-start flex flex-col gap-5">
          <div className="rounded-lg border border-border bg-card/60 p-4">
            <p className="mb-3 font-mono text-[11px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
              New initiative
            </p>
            <NewInitiative projectId={project.id} />
          </div>

          <ConversationRail
            scope={{ projectId: project.id }}
            advisorUrl={`/api/projects/${project.id}/advisor`}
            mode="reasoning across the project"
            subtitle="the whole project — your strategic thinking partner"
            intro="Ask the Advisor about the project as a whole — how it's going, what to build next, or whether anything contradicts across initiatives."
            discoverable
          />
        </div>
      </div>
    </main>
  );
}
