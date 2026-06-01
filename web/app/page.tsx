import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { listInitiatives } from "@/lib/api";
import NewInitiative from "./NewInitiative";

// The dashboard reflects live state — initiatives are created and advanced out of band.
export const dynamic = "force-dynamic";

const STAGES = ["discover", "shape", "bet", "decompose", "implement", "verify", "learn"];

function StageBadge({ stage }: { stage: string }) {
  const i = STAGES.indexOf(stage);
  const pos = i < 0 ? "" : `${i + 1}/${STAGES.length}`;
  return (
    <span className="flex shrink-0 items-center gap-1.5 font-mono text-[10px] tracking-widest text-accent-deep uppercase">
      <span className="size-1.5 rounded-full bg-primary" />
      {stage}
      {pos && <span className="text-ink-faint normal-case">· {pos}</span>}
    </span>
  );
}

export default async function Home() {
  const initiatives = await listInitiatives();

  return (
    <main className="relative z-10 mx-auto max-w-3xl px-5 py-16">
      <header className="animate-rise">
        <span className="font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
          Doen
        </span>
        <h1 className="mt-3 font-serif text-[clamp(2rem,5vw,3rem)] leading-[1.05] font-medium tracking-tight">
          The intent layer above your executors.
        </h1>
        <p className="mt-3 max-w-[48ch] text-muted-foreground">
          Every initiative you&apos;re steering. Open one to shape its spec, steer the decisions
          agents raise, and judge the work.
        </p>
        <NewInitiative />
      </header>

      <section className="animate-rise [animation-delay:120ms] mt-10">
        <h2 className="flex items-center gap-2 font-mono text-[11.5px] font-semibold tracking-[0.13em] text-ink-soft uppercase">
          Initiatives
          <span className="font-normal tracking-normal text-ink-faint normal-case">
            · {initiatives.length}
          </span>
        </h2>

        {initiatives.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">
            No initiatives yet — create one to get started.
          </p>
        ) : (
          <ul className="mt-4 space-y-2.5">
            {initiatives.map((i) => (
              <li key={i.id}>
                <Link
                  href={`/specs/${i.id}`}
                  className="group block rounded-lg border border-border bg-card/60 px-5 py-4 transition-colors hover:bg-card"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <h3 className="truncate font-serif text-[19px] leading-snug">
                        {i.title ?? i.id}
                      </h3>
                      <p className="mt-1 font-mono text-[11px] text-ink-faint">{i.id}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <StageBadge stage={i.stage} />
                      <ArrowRight className="size-4 text-ink-faint transition-transform group-hover:translate-x-0.5" />
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
