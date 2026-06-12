import React from "react";
import { getProject, getSpec } from "@/lib/api";
import { cn, stateMode } from "@/lib/utils";
import { SetBreadcrumb } from "@/app/_shell/breadcrumb";
import ConversationRail from "./ConversationRail";
import CriteriaVerification from "./CriteriaVerification";
import GuidedReview from "./GuidedReview";
import InitiativeStatus from "./InitiativeStatus";
import LearnStage from "./LearnStage";
import ResetConversationLink from "./ResetConversationLink";
import SpecActions from "./SpecActions";
import SpecDocument from "./SpecDocument";
import { SpecProvider } from "./spec-context";
import SpecTitle from "./SpecTitle";
import SteeringRail from "./SteeringRail";
import InitiativeTypeBadge from "./InitiativeTypeBadge";
import NextStepHint from "./NextStepHint";
import type { InitiativeType } from "@/lib/types";

const STATES = ["draft", "building", "learning", "complete"];

const RAIL_INTRO: Record<string, Record<InitiativeType, string>> = {
  draft: {
    engineering:
      "Shape this spec with the Advisor — describe what you want to build, challenge what's here, ask it to propose constraints or acceptance criteria, or request a full first draft.",
    research:
      "Shape the investigation with the Advisor — clarify the question you're asking, the constraints on methodology, the criteria that will tell you the investigation succeeded, or request a full first draft.",
  },
  building: {
    engineering:
      "Steer the build — ask whether something is in scope, question an implementation approach, check whether evidence covers a criterion, or ask the Advisor to flag risks.",
    research:
      "Investigate with the Advisor — share findings, ask it to surface contradictions, check whether a finding satisfies a criterion, or ask it to recommend a conclusion.",
  },
  learning: {
    engineering:
      "Reflect on the build with the Advisor — what matched the spec, what surprised you, what to carry forward. It can help you draft the retrospective or surface patterns from past initiatives.",
    research:
      "Reflect on the investigation with the Advisor — what the findings showed against the original question, what was unexpected, and what the next initiative in this space should know.",
  },
  complete: {
    engineering:
      "This initiative is closed. Ask the Advisor what was learned here and how those outcomes should inform the next piece of work.",
    research:
      "This investigation is closed. Ask the Advisor what the findings imply for future work or how this research should inform the next initiative.",
  },
};

const RAIL_HINT: Record<string, Record<InitiativeType, string | undefined>> = {
  draft: {
    engineering: "shape this initiative: [your idea]",
    research: "shape this initiative: [your research question]",
  },
  building: {
    engineering: "is [X] covered by the acceptance criteria?",
    research: "does this finding satisfy criterion [X]?",
  },
  learning: {
    engineering: "draft the retrospective",
    research: "draft the retrospective",
  },
  complete: { engineering: undefined, research: undefined },
};

// BD-15: "building" stage is labelled "Investigating" for research initiatives.
function stateLabel(s: string, initiativeType: InitiativeType): string {
  if (s === "building" && initiativeType === "research") return "investigating";
  return s;
}

function StateStepper({ state, initiativeType }: { state: string; initiativeType: InitiativeType }) {
  const current = Math.max(0, STATES.indexOf(state));
  return (
    <nav aria-label="lifecycle" className="flex items-center gap-0">
      {STATES.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <React.Fragment key={s}>
            {i > 0 && (
              <div className={cn("mx-2 h-px w-8 shrink-0", done ? "bg-confirmed" : "bg-border")} />
            )}
            <div className="flex items-center gap-1.5">
              <span
                className={cn(
                  "size-2 shrink-0 rounded-full",
                  done && "bg-confirmed",
                  active && "bg-primary ring-2 ring-primary/20",
                  !done && !active && "border border-border bg-transparent",
                )}
              />
              <span
                className={cn(
                  "text-[13px]",
                  done && "text-confirmed-foreground",
                  active && "font-semibold text-primary",
                  !done && !active && "text-ink-faint",
                )}
              >
                {stateLabel(s, initiativeType)}
              </span>
            </div>
          </React.Fragment>
        );
      })}
      <span className="ml-auto font-mono text-[11px] italic text-ink-faint">
        state follows the work
      </span>
    </nav>
  );
}

export default async function SpecPage({
  params,
}: {
  params: Promise<{ projectId: string; initiativeId: string }>;
}) {
  const { projectId, initiativeId } = await params;
  const spec = await getSpec(initiativeId);

  if (!spec) {
    return (
      <main className="relative z-10 mx-auto max-w-3xl px-4 py-16">
        <p className="text-muted-foreground">
          No spec found for <code className="font-mono">{initiativeId}</code>.
        </p>
      </main>
    );
  }

  const project = await getProject(projectId);
  const itype = spec.initiative_type ?? "engineering";

  return (
    <main className="relative z-10 mx-auto max-w-[1180px] px-5 py-8 md:px-8">
      {/* Breadcrumb uses short_id which is stable from creation — no need for reactivity here */}
      <SetBreadcrumb
        crumbs={[
          { label: project?.name ?? projectId, href: `/${projectId}` },
          { label: spec.short_id ?? spec.title },
        ]}
      />

      {/* one shared spec for both surfaces (0012 u3): the rail's guided review and the document
          read/write the same spec, so confirming in the rail builds up the document live.
          Header lives inside SpecProvider so SpecTitle can read the live spec title — the
          provisional fallback title updates without waiting for the full RSC refresh. */}
      <SpecProvider initialSpec={spec}>
        <header className="animate-rise">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
                Initiative
              </span>
              <InitiativeTypeBadge />
            </div>
            <span className="flex items-center gap-2 font-mono text-[11px]">
              <span className="size-[7px] rounded-full bg-confirmed animate-live" />
              {spec.short_id && (
                <span className="font-semibold tracking-wide text-accent-deep">
                  {spec.short_id}
                </span>
              )}
              <span className="text-ink-faint">{spec.initiative_id}</span>
            </span>
          </div>
          <h1 className="mt-2 max-w-[20ch] font-serif text-[clamp(1.9rem,3.4vw,2.6rem)] leading-[1.08] font-medium tracking-tight">
            <SpecTitle fallback={spec.title} />
          </h1>
          <div className="mt-4 border-t border-border pt-3.5">
            <StateStepper state={spec.state} initiativeType={itype} />
          </div>
        </header>
        <InitiativeStatus />
        <NextStepHint />
        <div className="mt-7 grid grid-cols-1 items-start gap-7 md:grid-cols-[1fr_380px]">
          <section>
            <SpecDocument />
            {(spec.state === "building" ||
              spec.state === "learning" ||
              spec.state === "complete") && (
              <CriteriaVerification initiativeId={spec.initiative_id} />
            )}
            {(spec.state === "learning" || spec.state === "complete") && (
              <LearnStage
                initiativeId={spec.initiative_id}
                intent={spec.intent}
                initiativeType={spec.initiative_type}
              />
            )}
            <SpecActions projectId={projectId} />
          </section>
          <div className="sticky top-6 flex flex-col gap-6 self-start">
            <ConversationRail
              scope={{ initiativeId: spec.initiative_id }}
              advisorUrl={`/api/initiatives/${spec.initiative_id}/advisor`}
              mode={stateMode(spec.state)}
              intro={RAIL_INTRO[spec.state]?.[itype] ?? RAIL_INTRO.draft.engineering}
              hintPrompt={RAIL_HINT[spec.state]?.[itype]}
              specId={spec.initiative_id}
              review={<GuidedReview />}
            />
            <SteeringRail initiativeId={spec.initiative_id} initiativeType={itype} />
            <ResetConversationLink scope={{ initiativeId: spec.initiative_id }} />
          </div>
        </div>
      </SpecProvider>
    </main>
  );
}
