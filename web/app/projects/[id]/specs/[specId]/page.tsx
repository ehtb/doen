import { redirect } from "next/navigation";

import { getProject, getSpecByRef } from "@/lib/api";
import { cn, stateMode } from "@/lib/utils";
import { SetBreadcrumb } from "@/app/_shell/breadcrumb";
import ConversationRail from "./ConversationRail";
import GuidedReview from "./GuidedReview";
import LearnStage from "./LearnStage";
import NextStepHint from "./NextStepHint";
import SpecActions from "./SpecActions";
import SpecDocument from "./SpecDocument";
import { SpecProvider } from "./spec-context";
import SteeringRail from "./SteeringRail";
import WorkUnits from "./WorkUnits";

// The three inferred lifecycle states (0011). There is no manual advance — the state is a read
// of the work units + learn record, so this stepper only reflects where the initiative sits.
const STATES = ["draft", "building", "complete"];

function StateStepper({ state }: { state: string }) {
  const current = Math.max(0, STATES.indexOf(state));
  return (
    <nav aria-label="lifecycle" className="flex flex-wrap items-center gap-x-1 gap-y-2">
      {STATES.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div
            key={s}
            className={cn(
              "flex items-center gap-2 px-3 py-0.5 font-mono text-[11px] tracking-wide capitalize",
              done && "text-ink-soft",
              active && "font-semibold text-accent-deep",
              !done && !active && "text-ink-faint",
            )}
          >
            <span
              className={cn(
                "size-2 rounded-full border",
                done && "border-ink-soft bg-ink-soft",
                active && "border-primary bg-primary ring-3 ring-primary/15",
                !done && !active && "border-border",
              )}
            />
            {s}
          </div>
        );
      })}
    </nav>
  );
}

export default async function SpecPage({
  params,
}: {
  params: Promise<{ id: string; specId: string }>;
}) {
  const { id: projectId, specId } = await params;
  // u5 (a10): the URL key is the short, per-project ref (bd-12-slug); resolve it — or a legacy
  // long id — to the spec, then normalise the URL to the canonical slug so stale links redirect.
  const spec = await getSpecByRef(projectId, specId);

  if (!spec) {
    return (
      <main className="relative z-10 mx-auto max-w-3xl px-4 py-16">
        <p className="text-muted-foreground">
          No spec found for <code className="font-mono">{specId}</code>.
        </p>
      </main>
    );
  }

  if (spec.short_slug && specId !== spec.short_slug) {
    redirect(`/projects/${projectId}/specs/${spec.short_slug}`);
  }

  const project = await getProject(projectId);

  return (
    <main className="relative z-10 mx-auto max-w-[1180px] px-5 py-8 md:px-8">
      {/* Doen -> Project -> this initiative; the persistent header renders the trail */}
      <SetBreadcrumb
        crumbs={[
          { label: project?.name ?? projectId, href: `/projects/${projectId}` },
          { label: spec.short_id ?? spec.title },
        ]}
      />
      <header className="animate-rise">
        <div className="flex items-baseline justify-between gap-4">
          <span className="font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
            Initiative
          </span>
          <span className="flex items-center gap-2 font-mono text-[11px]">
            <span className="size-[7px] rounded-full bg-confirmed animate-live" />
            {spec.short_id && (
              <span className="font-semibold tracking-wide text-accent-deep">{spec.short_id}</span>
            )}
            <span className="text-ink-faint">{spec.initiative_id}</span>
          </span>
        </div>
        <h1 className="mt-2 max-w-[20ch] font-serif text-[clamp(1.9rem,3.4vw,2.6rem)] leading-[1.08] font-medium tracking-tight">
          {spec.title}
        </h1>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3.5">
          <StateStepper state={spec.state} />
          <span className="font-mono text-[10px] tracking-wide text-ink-faint lowercase">
            state follows the work — no manual advance
          </span>
        </div>
      </header>

      {/* one shared spec for both surfaces (0012 u3): the rail's guided review and the document
          read/write the same spec, so confirming in the rail builds up the document live. */}
      <SpecProvider initialSpec={spec}>
        <NextStepHint />
        <div className="mt-7 flex flex-wrap items-start gap-7">
          <section className="min-w-80 flex-[1_1_560px]">
            <SpecDocument />
            <WorkUnits initiativeId={spec.initiative_id} acceptance={spec.acceptance} />
            {(spec.state === "building" || spec.state === "complete") && (
              <LearnStage
                initiativeId={spec.initiative_id}
                intent={spec.intent}
                acceptance={spec.acceptance}
              />
            )}
            <SpecActions projectId={projectId} />
          </section>
          <div className="sticky top-6 flex min-w-80 flex-[1_1_380px] flex-col gap-6 self-start">
            <ConversationRail
              messagesUrl={`/api/initiatives/${spec.initiative_id}/messages`}
              advisorUrl={`/api/initiatives/${spec.initiative_id}/advisor`}
              mode={stateMode(spec.state)}
              intro="Talk to the Advisor — it knows this spec, where it stands, and what past initiatives learned."
              shapeHint={spec.state === "draft"}
              specId={spec.initiative_id}
              review={<GuidedReview />}
            />
            <SteeringRail initiativeId={spec.initiative_id} />
          </div>
        </div>
      </SpecProvider>
    </main>
  );
}
