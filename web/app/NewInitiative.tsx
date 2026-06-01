"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// Creation IS shaping (0011 C2/a3): you describe what you want from within a project, and the
// Advisor drafts the whole spec — title, intent, constraints, discretion, criteria, units — as
// proposals you confirm item by item. No title-first step, no project picker (the screen fixes it).
export default function NewInitiative({ projectId }: { projectId: string }) {
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

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
      router.push(`/projects/${projectId}/specs/${init.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        shape();
      }}
    >
      <Textarea
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
        className="text-[13px]"
      />
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={busy || description.trim().length === 0}>
          {busy ? <Loader2 className="animate-spin" /> : <Sparkles />}
          {busy ? "Shaping…" : "Shape a new initiative"}
        </Button>
        {error ? (
          <span className="font-mono text-xs text-proposed-foreground">{error}</span>
        ) : (
          <span className="font-mono text-[10.5px] text-ink-faint">
            the Advisor sizes the spec to the work — a fix stays light, a feature gets the full
            structure
          </span>
        )}
      </div>
    </form>
  );
}
