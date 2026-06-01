"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

const STAGES = ["discover", "shape", "bet", "decompose", "implement", "verify", "learn"];

export default function StageControls({
  initiativeId,
  stage,
}: {
  initiativeId: string;
  stage: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const i = STAGES.indexOf(stage);
  const prev = i > 0 ? STAGES[i - 1] : null;
  const next = i >= 0 && i < STAGES.length - 1 ? STAGES[i + 1] : null;

  async function move(target: string | null) {
    if (!target || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/initiatives/${initiativeId}/stage`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ stage: target }),
      });
      if (!res.ok) throw new Error(`stage change failed (${res.status})`);
      router.refresh(); // re-render the server page so the stepper + stage reflect the move
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {error && <span className="font-mono text-[10px] text-proposed-foreground">{error}</span>}
      <Button
        size="sm"
        variant="ghost"
        disabled={busy || !prev}
        onClick={() => move(prev)}
        title={prev ? `Back to ${prev}` : "Already at the first stage"}
        className="h-7 px-2 font-mono text-[11px] tracking-wide"
      >
        <ChevronLeft /> back
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={busy || !next}
        onClick={() => move(next)}
        title={next ? `Advance to ${next}` : "Already at the final stage"}
        className="h-7 px-2.5 font-mono text-[11px] tracking-wide"
      >
        advance <ChevronRight />
      </Button>
    </div>
  );
}
