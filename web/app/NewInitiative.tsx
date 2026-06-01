"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { consumeInitiativeDraft, PREFILL_EVENT } from "@/lib/initiativeDraft";

// Creation IS shaping (0011 C2/a3): you describe what you want from within a project, and the
// Advisor drafts the whole spec — title, intent, constraints, discretion, criteria, units — as
// proposals you confirm item by item. No title-first step, no project picker (the screen fixes it).
export default function NewInitiative({ projectId }: { projectId: string }) {
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  // The Textarea doesn't forward a ref, so we scroll via a wrapper and focus by id.
  const formRef = useRef<HTMLFormElement>(null);
  const fieldId = `new-initiative-${projectId}`;

  // BD-1 u3: the project rail's "Create initiative from this" hands a synthesised description here
  // (description only — every other part of the spec is still drafted from it). Pre-fill it, bring
  // the form into view, and focus, so the deliberate act stays the human's but the typing is saved.
  const prefill = useCallback(
    (text: string) => {
      setDescription(text);
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

  useEffect(() => {
    // survives a route transition / reload: consume any draft stashed before this mounted.
    const stashed = consumeInitiativeDraft(projectId);
    if (stashed) prefill(stashed);
    // same-page hand-off: the rail dispatches this when the form is already mounted beside it.
    const onPrefill = (e: Event) => {
      const detail = (
        e as CustomEvent<{ projectId: string; description?: string }>
      ).detail;
      if (detail?.projectId !== projectId) return;
      const draft =
        consumeInitiativeDraft(projectId) ?? detail.description ?? null;
      if (draft) prefill(draft);
    };
    window.addEventListener(PREFILL_EVENT, onPrefill);
    return () => window.removeEventListener(PREFILL_EVENT, onPrefill);
  }, [projectId, prefill]);

  async function shape() {
    const d = description.trim();
    if (!d || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}/initiatives/shape`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ description: d }),
      });
      if (!res.ok) throw new Error(`couldn't shape that (${res.status})`);
      const init = await res.json();
      // land in the freshly-shaped spec to review and confirm the proposals
      router.push(`/${projectId}/${init.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <form
      ref={formRef}
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        shape();
      }}
    >
      <Textarea
        id={fieldId}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Describe what you want — a feature or a fix. The Advisor drafts the spec; you confirm it."
        rows={3}
        disabled={busy}
        // Cmd/Ctrl+Enter submits without forcing the mouse over to the button
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            shape();
          }
        }}
        className="resize-none border-rail-border bg-rail-card text-rail-foreground placeholder:text-rail-muted"
      />
      <div className="flex items-center gap-3">
        <Button
          type="submit"
          disabled={busy || description.trim().length === 0}
        >
          {busy ? <Loader2 className="animate-spin" /> : <Sparkles />}
          {busy ? "Shaping…" : "Shape a new initiative"}
        </Button>
        {error ? (
          <span className="font-mono text-xs text-proposed-foreground">
            {error}
          </span>
        ) : (
          <span className="font-mono text-[10.5px] text-ink-faint">
            the Advisor sizes the spec to the work — a fix stays light, a
            feature gets the full structure
          </span>
        )}
      </div>
    </form>
  );
}
