"use client";

import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ProjectSynthesisResponse, WhatWeKnow } from "@/lib/types";
import { isRecent, timeago } from "@/lib/timeago";

export default function WhatWeKnowModal({
  projectId,
  completedCount,
}: {
  projectId: string;
  completedCount: number;
}) {
  const [open, setOpen] = useState(false);
  const [whatWeKnow, setWhatWeKnow] = useState<WhatWeKnow | null>(null);
  const [synthesizedAt, setSynthesizedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const fetched = useRef(false);

  async function fetchSynthesis() {
    if (completedCount === 0) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/synthesis`, { cache: "no-store" });
      const json: ProjectSynthesisResponse | null = res.ok ? await res.json() : null;
      setWhatWeKnow(json?.what_we_know ?? null);
      setSynthesizedAt(json?.synthesized_at ?? null);
    } catch {}
    finally { setLoading(false); }
  }

  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    fetchSynthesis();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (open) fetchSynthesis();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (completedCount === 0) return null;

  return (
    <>
      <span className="relative inline-flex">
        <Button
          size="xs"
          variant="outline"
          shadow="none"
          onClick={() => setOpen(true)}
        >
          <Sparkles className="size-3 text-primary/60" />
          What we know
        </Button>
        {synthesizedAt && isRecent(synthesizedAt) && (
          <span
            className="absolute -right-1 -top-1 size-2 rounded-full bg-confirmed"
            title={`Updated ${timeago(synthesizedAt)}`}
          />
        )}
      </span>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[800px] max-w-[800px] bg-[#FDFAF5]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 font-serif text-[18px] font-normal">
              <Sparkles className="size-3.5 text-primary/60" />
              What we know
            </DialogTitle>
          </DialogHeader>

          <div className="rounded-md border border-border/50 bg-muted/30 px-3.5 py-3">
            <p className="text-[12.5px] leading-relaxed text-ink-soft">
              A cross-initiative synthesis covering recurring patterns, validated and invalidated assumptions, and how completed work relates to the project's intent. Generated from project memory and initiative retrospectives. Requires 5 completed initiatives; updates every 3 thereafter.
            </p>
            {synthesizedAt && (
              <p className="mt-1.5 font-mono text-[10.5px] text-ink-faint">
                Last updated{" "}
                {new Date(synthesizedAt).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}
                {" · "}based on {completedCount} completed initiative{completedCount === 1 ? "" : "s"}
              </p>
            )}
          </div>

          <div className="max-h-[50vh] overflow-y-auto">
            {loading && (
              <p className="animate-pulse font-mono text-[12px] text-ink-faint">
                Advisor is reviewing project history…
              </p>
            )}
            {!loading && !whatWeKnow && (
              <p className="font-mono text-[12px] text-ink-faint">
                Synthesis available after 5 completed initiatives (
                {completedCount} so far).
              </p>
            )}
            {!loading && whatWeKnow && (
              <div className="space-y-5">
                <Section label="Patterns" content={whatWeKnow.patterns} />
                <Section label="Assumptions" content={whatWeKnow.assumptions} />
                <Section
                  label="Intent alignment"
                  content={whatWeKnow.intent_alignment}
                />
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Section({ label, content }: { label: string; content: string }) {
  return (
    <div>
      <div className="mb-1.5 font-mono text-[9.5px] tracking-[0.1em] text-ink-faint uppercase">
        {label}
      </div>
      <p className="text-[13px] leading-relaxed text-foreground/80">{content}</p>
    </div>
  );
}
