"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { FlaskConical, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  consumeInitiativeDraft,
  PREFILL_EVENT,
  type InitiativeDraft,
} from "@/lib/initiativeDraft";

// Creation IS shaping (0011 C2/a3): you describe what you want from within a project, and the
// Advisor drafts the whole spec — title, intent, constraints, discretion, criteria, units — as
// proposals you confirm item by item. No title-first step, no project picker (the screen fixes it).
export default function NewInitiative({ projectId }: { projectId: string }) {
  const [description, setDescription] = useState("");
  const [busyType, setBusyType] = useState<"engineering" | "research" | null>(null);
  const busy = busyType !== null;
  const [error, setError] = useState<string | null>(null);
  // BD-22: observation_id stashed alongside the draft — resolve after creation.
  const pendingObservationId = useRef<string | undefined>(undefined);
  const router = useRouter();
  // The Textarea doesn't forward a ref, so we scroll via a wrapper and focus by id.
  const formRef = useRef<HTMLFormElement>(null);
  const fieldId = `new-initiative-${projectId}`;

  // BD-1 u3: the project rail's "Create initiative from this" hands a synthesised description here.
  // Pre-fill it, bring the form into view, and focus — the deliberate act stays the human's.
  // BD-20: also accepts an optional initiative type from the discovery conversation.
  // BD-22: also accepts an optional observation_id to resolve after creation.
  const prefill = useCallback(
    (draft: InitiativeDraft) => {
      setDescription(draft.description);
      pendingObservationId.current = draft.observation_id;
      requestAnimationFrame(() => {
        formRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
        document.getElementById(fieldId)?.focus();
      });
    },
    [fieldId],
  );

  // Warn if the user tries to close or navigate away while the creation call is in-flight.
  useEffect(() => {
    if (!busy) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

  useEffect(() => {
    // survives a route transition / reload: consume any draft stashed before this mounted.
    const stashed = consumeInitiativeDraft(projectId);
    if (stashed) prefill(stashed);
    // same-page hand-off: the rail dispatches this when the form is already mounted beside it.
    const onPrefill = (e: Event) => {
      const detail = (
        e as CustomEvent<{
          projectId: string;
          description?: string;
          initiative_type?: string;
          observation_id?: string;
        }>
      ).detail;
      if (detail?.projectId !== projectId) return;
      // consumeInitiativeDraft first (includes type + observation_id from sessionStorage); fall back to event detail.
      const draft =
        consumeInitiativeDraft(projectId) ??
        (detail.description
          ? {
              description: detail.description,
              initiative_type:
                detail.initiative_type as InitiativeDraft["initiative_type"],
              observation_id: detail.observation_id,
            }
          : null);
      if (draft) prefill(draft);
    };
    window.addEventListener(PREFILL_EVENT, onPrefill);
    return () => window.removeEventListener(PREFILL_EVENT, onPrefill);
  }, [projectId, prefill]);

  async function shapeAs(initiative_type: "engineering" | "research") {
    const d = description.trim();
    if (!d || busy) return;
    setBusyType(initiative_type);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}/initiatives/shape`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ description: d, initiative_type }),
      });
      if (!res.ok) throw new Error(`couldn't shape that (${res.status})`);
      const init = await res.json();
      // BD-22: if this initiative was created from an observation, resolve that observation now.
      const obsId = pendingObservationId.current;
      if (obsId) {
        pendingObservationId.current = undefined;
        fetch(`/api/observations/${obsId}/resolve`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ initiative_id: init.id }),
        }).catch(() => {});
      }
      setBusyType(null);
      // land in the freshly-shaped spec to review and confirm the proposals
      router.push(`/${projectId}/${init.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusyType(null);
    }
  }

  return (
    <form
      ref={formRef}
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        shapeAs("engineering");
      }}
    >
      <Textarea
        id={fieldId}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Describe what you want — a feature, a fix, or an investigation. The Advisor drafts the spec; you confirm it."
        rows={3}
        disabled={busy}
        // Cmd/Ctrl+Enter submits without forcing the mouse over to the button
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            shapeAs("engineering");
          }
        }}
        className="resize-none border-rail-border bg-rail-card text-rail-foreground placeholder:text-rail-muted"
      />

      <div className="mt-2 flex items-center justify-between">
        {error ? (
          <span className="font-mono text-xs text-proposed-foreground">
            {error}
          </span>
        ) : (
          <span className="font-mono text-[10px] tracking-wide text-rail-muted">
            ⌘↵ to send
          </span>
        )}
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy || description.trim().length === 0}
            onClick={() => shapeAs("research")}
            className="border-confirmed/40 text-confirmed-foreground hover:bg-confirmed/10 hover:border-confirmed/60"
          >
            {busyType === "research" ? <Loader2 className="animate-spin" /> : <FlaskConical />}
            {busyType === "research" ? "Shaping…" : "Research"}
          </Button>
          <Button
            type="submit"
            size="sm"
            disabled={busy || description.trim().length === 0}
          >
            {busyType === "engineering" ? <Loader2 className="animate-spin" /> : <Sparkles />}
            {busyType === "engineering" ? "Shaping…" : "Shape"}
          </Button>
        </div>
      </div>
    </form>
  );
}
