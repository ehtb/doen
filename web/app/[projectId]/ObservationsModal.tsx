"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  GitBranch,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Observation, ProjectSynthesisResponse } from "@/lib/types";
import { stashInitiativeDraft } from "@/lib/initiativeDraft";
import { isRecent, timeago } from "@/lib/timeago";
import { cn } from "@/lib/utils";

export default function ObservationsModal({
  projectId,
  completedCount,
}: {
  projectId: string;
  completedCount: number;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [synthesizedAt, setSynthesizedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resolvedOpen, setResolvedOpen] = useState(false);
  const fetched = useRef(false);

  // Fetch on mount so synthesizedAt is available for the button indicator before
  // the dialog is opened. Re-fetch on dialog open to surface any new observations.
  async function fetchSynthesis() {
    if (completedCount === 0) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/synthesis`, { cache: "no-store" });
      const json: ProjectSynthesisResponse | null = res.ok ? await res.json() : null;
      setObservations(json?.observations ?? []);
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
    if (dialogOpen) fetchSynthesis();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dialogOpen]);

  const openObs = observations.filter((o) => o.status === "open");
  const resolvedObs = observations.filter(
    (o) => o.status === "resolved" || o.status === "rejected",
  );

  if (completedCount === 0) return null;

  return (
    <>
      <span className="relative inline-flex">
        <Button
          size="xs"
          variant="outline"
          shadow="none"
          onClick={() => setDialogOpen(true)}
        >
          <Sparkles className="size-3 text-primary/60" />
          Observations
          {openObs.length > 0 && (
            <span className="ml-0.5 rounded-full bg-primary/15 px-1.5 font-mono text-[9px] text-accent-deep">
              {openObs.length}
            </span>
          )}
        </Button>
        {synthesizedAt && isRecent(synthesizedAt) && (
          <span
            className="absolute -right-1 -top-1 size-2 rounded-full bg-confirmed"
            title={`Updated ${timeago(synthesizedAt)}`}
          />
        )}
      </span>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="w-[640px] max-w-[640px] bg-[#FDFAF5]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 font-serif text-[18px] font-normal">
              <Sparkles className="size-3.5 text-primary/60" />
              Advisor observations
            </DialogTitle>
          </DialogHeader>

          <div className="rounded-md border border-border/50 bg-muted/30 px-3.5 py-3">
            <p className="text-[12.5px] leading-relaxed text-ink-soft">
              The Advisor reviews completed initiatives every 3 completions and surfaces patterns, risks, or opportunities that haven't been acted on yet. Each observation can be shaped into a new initiative or dismissed.
            </p>
            {synthesizedAt && (
              <p className="mt-1.5 font-mono text-[10.5px] text-ink-faint">
                Last generated{" "}
                {new Date(synthesizedAt).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}
                {" · "}after {completedCount} completed initiative{completedCount === 1 ? "" : "s"}
              </p>
            )}
          </div>

          <div className="max-h-[55vh] space-y-2 overflow-y-auto">
            {loading && (
              <p className="animate-pulse font-mono text-[12px] text-ink-faint">
                Advisor is reviewing project history…
              </p>
            )}
            {!loading && observations.length === 0 && (
              <p className="font-mono text-[12px] text-ink-faint">
                No observations yet.
              </p>
            )}
            {!loading && (
              <>
                {openObs.map((obs) => (
                  <ObservationCard
                    key={obs.id}
                    observation={obs}
                    projectId={projectId}
                    onClose={() => setDialogOpen(false)}
                    onOptimisticResolve={(id) =>
                      setObservations((prev) =>
                        prev.map((o) =>
                          o.id === id ? { ...o, status: "resolved" } : o,
                        ),
                      )
                    }
                    onOptimisticReject={(id) =>
                      setObservations((prev) =>
                        prev.map((o) =>
                          o.id === id ? { ...o, status: "rejected" } : o,
                        ),
                      )
                    }
                  />
                ))}

                {resolvedObs.length > 0 && (
                  <div className="rounded-lg border border-border bg-card/20 px-4 py-2">
                    <button
                      type="button"
                      onClick={() => setResolvedOpen((v) => !v)}
                      className="flex w-full items-center justify-between font-mono text-[10px] tracking-[0.1em] text-ink-faint uppercase"
                    >
                      <span className="flex items-center gap-1.5">
                        <CheckCircle2 className="size-3" />
                        {resolvedObs.length} past observation
                        {resolvedObs.length === 1 ? "" : "s"}
                      </span>
                      {resolvedOpen ? (
                        <ChevronUp className="size-3" />
                      ) : (
                        <ChevronDown className="size-3" />
                      )}
                    </button>
                    {resolvedOpen && (
                      <div className="mt-2 space-y-3 border-t border-border pt-2">
                        {resolvedObs.map((obs) => (
                          <ResolvedObservation key={obs.id} observation={obs} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ObservationCard({
  observation,
  projectId,
  onClose,
  onOptimisticResolve,
  onOptimisticReject,
}: {
  observation: Observation;
  projectId: string;
  onClose: () => void;
  onOptimisticResolve: (id: string) => void;
  onOptimisticReject: (id: string) => void;
}) {
  const [confirmingReject, setConfirmingReject] = useState(false);

  const handleResolve = useCallback(() => {
    onOptimisticResolve(observation.id);
    onClose();
    stashInitiativeDraft(projectId, observation.content, undefined, observation.id);
    const formEl = document.getElementById(`new-initiative-${projectId}`);
    if (formEl) {
      formEl.scrollIntoView({ behavior: "smooth", block: "center" });
      formEl.focus();
    }
  }, [observation, projectId, onOptimisticResolve, onClose]);

  const handleRejectConfirm = useCallback(async () => {
    onOptimisticReject(observation.id);
    try {
      await fetch(`/api/observations/${observation.id}/reject`, {
        method: "POST",
        cache: "no-store",
      });
    } catch {}
  }, [observation.id, onOptimisticReject]);

  return (
    <div className="rounded-lg border border-border bg-card/40 px-4 py-3.5">
      <div className="mb-2 flex items-center gap-1.5 font-mono text-[10.5px] font-semibold tracking-[0.13em] text-accent-deep uppercase">
        <Sparkles className="size-3" />
        Advisor observation
      </div>
      <p className="text-sm leading-relaxed text-foreground/80">
        {observation.content}
      </p>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={handleResolve}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/8",
            "px-2.5 py-1 font-mono text-[10.5px] tracking-wide text-accent-deep",
            "transition-colors hover:border-primary/50 hover:bg-primary/15",
          )}
        >
          <GitBranch className="size-3" />
          Shape from this
        </button>
        {confirmingReject ? (
          <span className="inline-flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleRejectConfirm}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/8",
                "px-2.5 py-1 font-mono text-[10.5px] tracking-wide text-destructive/80",
                "transition-colors hover:bg-destructive/15",
              )}
            >
              Confirm dismiss
            </button>
            <button
              type="button"
              onClick={() => setConfirmingReject(false)}
              className="font-mono text-[10px] text-ink-faint hover:text-ink-soft"
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmingReject(true)}
            className={cn(
              "inline-flex items-center gap-1 rounded-md border border-border",
              "px-2.5 py-1 font-mono text-[10.5px] tracking-wide text-ink-faint",
              "transition-colors hover:border-border/80 hover:text-ink-soft",
            )}
          >
            <X className="size-3" />
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}

function ResolvedObservation({ observation }: { observation: Observation }) {
  const isRejected = observation.status === "rejected";
  return (
    <div className="space-y-0.5">
      <p className="text-[12.5px] leading-relaxed text-foreground/40 line-through decoration-foreground/20">
        {observation.content}
      </p>
      {isRejected ? (
        <p className="font-mono text-[10px] text-ink-faint">dismissed</p>
      ) : (
        observation.resolved_initiative_id && (
          <p className="font-mono text-[10px] text-ink-faint">
            → resolved as{" "}
            <span className="text-ink-soft">
              {observation.resolved_initiative_id}
            </span>
          </p>
        )
      )}
    </div>
  );
}
