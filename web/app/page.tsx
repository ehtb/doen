import Link from "next/link";
import { ArrowRight, Layers, Sparkles } from "lucide-react";

import { listInitiatives, listProjects } from "@/lib/api";
import type { Initiative, Project } from "@/lib/types";
import { SetBreadcrumb } from "@/app/_shell/breadcrumb";
import NewProject from "./NewProject";

// The dashboard reflects live state — projects + initiatives change out of band.
export const dynamic = "force-dynamic";

// A project at the top level (0010): its intent + how many initiatives it groups, linking
// into the project dashboard where the Advisor reasons across the whole body of work.
function ProjectCard({ project, count }: { project: Project; count: number }) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className="group block rounded-lg border border-border bg-card/60 px-5 py-4 transition-colors hover:bg-card"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 font-serif text-[19px] leading-snug">
            <Layers className="size-4 shrink-0 text-accent-deep" />
            {project.name}
          </h3>
          {project.intent && (
            <p className="mt-1.5 line-clamp-2 max-w-[60ch] text-[13px] leading-relaxed text-muted-foreground">
              {project.intent}
            </p>
          )}
          <p className="mt-2 font-mono text-[10.5px] tracking-widest text-ink-faint uppercase">
            {count} initiative{count === 1 ? "" : "s"}
          </p>
        </div>
        <ArrowRight className="mt-1 size-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </div>
    </Link>
  );
}

export default async function Home() {
  const [projects, initiatives] = await Promise.all([listProjects(), listInitiatives()]);
  const countFor = (projectId: string) =>
    initiatives.filter((i: Initiative) => i.project_id === projectId).length;

  return (
    <main className="relative z-10 mx-auto max-w-3xl px-5 py-16">
      {/* root is the top of the hierarchy — the header brand alone reads "Doen", no trail */}
      <SetBreadcrumb crumbs={[]} />
      <header className="animate-rise">
        <span className="font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
          Doen
        </span>
        <h1 className="mt-3 font-serif text-[clamp(2rem,5vw,3rem)] leading-[1.05] font-medium tracking-tight">
          The intent layer above your executors.
        </h1>
        <p className="mt-3 max-w-[48ch] text-muted-foreground">
          Every initiative you&apos;re steering, grouped into projects. Open a project to reason
          across its history and start new initiatives in it.
        </p>
      </header>

      <section className="animate-rise mt-10 [animation-delay:80ms]">
        <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
          Projects
          <span className="font-normal tracking-normal text-ink-faint normal-case">
            · {projects.length}
          </span>
        </h2>

        {projects.length === 0 ? (
          // First visit (0013 u4): the Advisor itself greets and walks the user from zero — no
          // tour, no modal. The next step (creating a project) is inline and prominent.
          <div className="animate-rise mt-5 rounded-2xl border border-rail-border bg-rail p-6 text-rail-foreground">
            <span className="flex items-center gap-1.5 font-mono text-[10px] font-semibold tracking-[0.14em] text-primary uppercase">
              <Sparkles className="size-3" /> Advisor
            </span>
            <h3 className="mt-2.5 font-serif text-[22px] leading-snug">
              Welcome — let&apos;s set up your first project.
            </h3>
            <p className="mt-2 max-w-[58ch] text-[14px] leading-relaxed text-rail-muted">
              Doen is where you decide what&apos;s worth building and steer it. I&apos;m the
              Advisor — I help you shape a living spec, then an executor builds against it and
              brings the decisions back to you. Start with a project: a container for related
              work. Name it and give it a one-sentence intent.
            </p>
            <div className="mt-4">
              <NewProject defaultOpen />
            </div>
            <p className="mt-4 max-w-[58ch] text-[13px] leading-relaxed text-rail-muted">
              Once it exists, describe your first initiative inside it and I&apos;ll draft the
              whole spec for you to correct — that&apos;s how the loop starts.
            </p>
          </div>
        ) : (
          <>
            <div className="mt-4">
              <NewProject />
            </div>
            <ul className="mt-5 space-y-2.5">
              {projects.map((p: Project) => (
                <li key={p.id}>
                  <ProjectCard project={p} count={countFor(p.id)} />
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </main>
  );
}
