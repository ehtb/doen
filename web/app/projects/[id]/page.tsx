import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, GitBranch, Layers } from "lucide-react";

import { getProjectDashboard } from "@/lib/api";
import { InitiativeCard, STATES } from "../../InitiativeCard";
import NewInitiative from "../../NewInitiative";
import ConversationRail from "./specs/[specId]/ConversationRail";

// The project as a whole — its grouped initiatives change live as they're created/advanced.
export const dynamic = "force-dynamic";

export default async function ProjectDashboardPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await getProjectDashboard(id);
  if (!data) notFound();

  const { project, initiatives, open_decisions, attention } = data;

  // State distribution across the project — a whole-project read of where the work sits (0011).
  const byState = STATES.map((s) => ({
    state: s,
    count: initiatives.filter((i) => i.state === s).length,
  })).filter((s) => s.count > 0);

  // The dot colour per lifecycle state — echoes the StateBadge so the groups read at a glance.
  const STATE_DOT: Record<string, string> = {
    draft: "bg-ink-soft",
    building: "bg-primary",
    complete: "bg-confirmed",
  };

  return (
    <main className="relative z-10 mx-auto max-w-[1180px] px-5 py-12 md:px-8">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 font-mono text-[11px] tracking-wide text-ink-faint uppercase transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> All projects
      </Link>

      <header className="animate-rise mt-5">
        <span className="flex items-center gap-1.5 font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
          <Layers className="size-3.5" /> Project
        </span>
        <h1 className="mt-3 font-serif text-[clamp(2rem,5vw,3rem)] leading-[1.05] font-medium tracking-tight">
          {project.name}
        </h1>
        {project.intent && (
          <p className="mt-4 max-w-[68ch] leading-relaxed text-muted-foreground">
            {project.intent}
          </p>
        )}

        {/* whole-project aggregate (a2): how much work, where it sits, open escalations */}
        <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[11px] text-ink-faint">
          <span>
            <span className="text-foreground">{initiatives.length}</span> initiative
            {initiatives.length === 1 ? "" : "s"}
          </span>
          {byState.map((s) => (
            <span key={s.state} className="tracking-widest uppercase">
              <span className="text-accent-deep">{s.count}</span> {s.state}
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <GitBranch className="size-3" />
            <span className={open_decisions > 0 ? "text-proposed-foreground" : "text-foreground"}>
              {open_decisions}
            </span>{" "}
            open decision{open_decisions === 1 ? "" : "s"}
          </span>
        </div>
      </header>

      <div className="mt-9 flex flex-wrap items-start gap-7">
        <section className="min-w-80 flex-[1_1_520px]">
          <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
            Initiatives
            <span className="font-normal tracking-normal text-ink-faint normal-case">
              · {initiatives.length}
            </span>
          </h2>

          {/* initiatives are started here, within the project (no orphan specs) */}
          <div className="mt-4">
            <NewInitiative projectId={project.id} />
          </div>

          {initiatives.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">
              No initiatives in this project yet — describe one above and the Advisor shapes it.
            </p>
          ) : (
            // grouped by lifecycle state (0011 a8) — where everything stands, at a glance, with
            // per-initiative attention indicators showing what needs the human.
            <div className="mt-5 space-y-7">
              {STATES.map((st) => {
                const group = initiatives.filter((i) => i.state === st);
                if (group.length === 0) return null;
                return (
                  <div key={st}>
                    <h3 className="flex items-center gap-2 font-mono text-[11px] font-semibold tracking-[0.16em] text-ink-soft uppercase">
                      <span className={`size-2 rounded-full ${STATE_DOT[st] ?? "bg-border"}`} />
                      {st}
                      <span className="font-normal tracking-normal text-ink-faint normal-case">
                        · {group.length}
                      </span>
                    </h3>
                    <ul className="mt-3 space-y-2.5">
                      {group.map((i) => (
                        <li key={i.id}>
                          <InitiativeCard initiative={i} attention={attention[i.id]} />
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* the project-level rail (a9/a10): the same Advisor, scoped to the whole project */}
        <div className="sticky top-6 min-w-80 flex-[1_1_360px] self-start">
          <ConversationRail
            messagesUrl={`/api/projects/${project.id}/messages`}
            advisorUrl={`/api/projects/${project.id}/advisor`}
            mode="reasoning across the project"
            subtitle="the whole project — your strategic thinking partner"
            intro="Ask the Advisor about the project as a whole — how it's going, what to build next, or whether anything contradicts across initiatives."
          />
        </div>
      </div>
    </main>
  );
}
