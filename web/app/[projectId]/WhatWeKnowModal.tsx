"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ProjectSynthesisResponse, WhatWeKnow } from "@/lib/types";

export default function WhatWeKnowModal({
  projectId,
  completedCount,
}: {
  projectId: string;
  completedCount: number;
}) {
  const [open, setOpen] = useState(false);
  const [whatWeKnow, setWhatWeKnow] = useState<WhatWeKnow | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || completedCount === 0) return;
    setLoading(true);
    fetch(`/api/projects/${projectId}/synthesis`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((json: ProjectSynthesisResponse | null) => {
        setWhatWeKnow(json?.what_we_know ?? null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open, projectId, completedCount]);

  if (completedCount === 0) return null;

  return (
    <>
      <Button
        size="xs"
        variant="outline"
        shadow="none"
        onClick={() => setOpen(true)}
      >
        <Sparkles className="size-3 text-primary/60" />
        What we know
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[800px] max-w-[800px] bg-[#FDFAF5]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 font-serif text-[18px] font-normal">
              <Sparkles className="size-3.5 text-primary/60" />
              What we know
            </DialogTitle>
          </DialogHeader>

          <div className="max-h-[60vh] overflow-y-auto">
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
