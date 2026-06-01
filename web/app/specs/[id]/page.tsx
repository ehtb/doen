import { getSpec } from "@/lib/api";
import { cn } from "@/lib/utils";
import LearnStage from "./LearnStage";
import SpecDocument from "./SpecDocument";
import StageControls from "./StageControls";
import SteeringRail from "./SteeringRail";
import WorkUnits from "./WorkUnits";

const STAGES = ["discover", "shape", "bet", "decompose", "implement", "verify", "learn"];

function LifecycleStepper({ stage }: { stage: string }) {
  const current = Math.max(0, STAGES.indexOf(stage));
  return (
    <nav aria-label="lifecycle" className="flex flex-wrap gap-x-1 gap-y-2">
      {STAGES.map((s, i) => {
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

export default async function SpecPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const spec = await getSpec(id);

  if (!spec) {
    return (
      <main className="relative z-10 mx-auto max-w-3xl px-4 py-16">
        <p className="text-muted-foreground">
          No spec found for <code className="font-mono">{id}</code>.
        </p>
      </main>
    );
  }

  return (
    <main className="relative z-10 mx-auto max-w-[1180px] px-5 py-8 md:px-8">
      <header className="animate-rise">
        <div className="flex items-baseline justify-between gap-4">
          <span className="font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
            Initiative
          </span>
          <span className="flex items-center gap-2 font-mono text-[11px] text-ink-faint">
            <span className="size-[7px] rounded-full bg-confirmed animate-live" />
            {spec.initiative_id}
          </span>
        </div>
        <h1 className="mt-2 max-w-[20ch] font-serif text-[clamp(1.9rem,3.4vw,2.6rem)] leading-[1.08] font-medium tracking-tight">
          {spec.title}
        </h1>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3.5">
          <LifecycleStepper stage={spec.stage} />
          <StageControls initiativeId={spec.initiative_id} stage={spec.stage} />
        </div>
      </header>

      <div className="mt-7 flex flex-wrap items-start gap-7">
        <section className="min-w-80 flex-[1_1_560px]">
          <SpecDocument initialSpec={spec} />
          <WorkUnits initiativeId={spec.initiative_id} acceptance={spec.acceptance} />
          {(spec.stage === "verify" || spec.stage === "learn") && (
            <LearnStage
              initiativeId={spec.initiative_id}
              intent={spec.intent}
              acceptance={spec.acceptance}
            />
          )}
        </section>
        <SteeringRail initiativeId={spec.initiative_id} />
      </div>
    </main>
  );
}
