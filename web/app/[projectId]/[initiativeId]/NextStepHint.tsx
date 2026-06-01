"use client";

import { useEffect, useState } from "react";
import { ArrowDown, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

const POLL_MS = 3000;

// The post-build, pre-learn moment was silent (0013 AC10): every unit verified, but nothing
// pointed at the next step. This is the nudge — it appears only when all units are done AND no
// learn memory has been captured yet, and links straight to the Learn section.
export default function NextStepHint() {
  const { spec } = useSpec();
  const [unitsAllDone, setUnitsAllDone] = useState(false);
  const [hasLearn, setHasLearn] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const [uRes, lRes] = await Promise.all([
          fetch(`/api/specs/${spec.initiative_id}/units`, { cache: "no-store" }),
          fetch(`/api/initiatives/${spec.initiative_id}/learn`, { cache: "no-store" }),
        ]);
        if (!alive) return;
        if (uRes.ok) {
          const us = (await uRes.json()) as Array<{ status: string }>;
          setUnitsAllDone(us.length > 0 && us.every((u) => u.status === "done"));
        }
        if (lRes.ok) {
          const learn = (await lRes.json()) as { memory?: unknown[] };
          setHasLearn((learn.memory ?? []).length > 0);
        }
      } catch {
        /* transient — keep the prior signal */
      }
    }
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [spec.initiative_id]);

  if (!unitsAllDone || hasLearn !== false) return null;

  return (
    <div className="animate-rise mt-5 flex flex-wrap items-center gap-4 rounded-xl border border-confirmed/40 bg-confirmed/5 px-4 py-3.5">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-confirmed/15 text-confirmed-foreground">
        <Check className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[10.5px] font-semibold tracking-widest text-confirmed-foreground uppercase">
          Last step
        </p>
        <p className="text-[13.5px] leading-relaxed text-foreground">
          The build shipped — every unit verified. Capture what you learned to complete the spec
          and write a memory the next initiative can retrieve.
        </p>
      </div>
      <Button asChild className="shadow-sm">
        <a href="#learn" className="inline-flex items-center gap-2">
          <ArrowDown /> Go to Learn
        </a>
      </Button>
    </div>
  );
}
