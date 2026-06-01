"use client";

import { useState } from "react";
import { Check, Loader2, Pencil, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// Inline intent editing on the project dashboard (0013 u2). The Advisor can still help if asked
// in the rail, but this is the direct edit path: a pencil reveals a textarea, saving PATCHes the
// intent and persists. An empty intent shows a directive prompt rather than nothing.
export default function ProjectIntent({
  projectId,
  intent,
}: {
  projectId: string;
  intent: string;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(intent);
  const [draft, setDraft] = useState(intent);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ intent: draft.trim() }),
      });
      if (!res.ok) throw new Error(`couldn't save (${res.status})`);
      const p = await res.json();
      setValue(p.intent ?? draft.trim());
      setEditing(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <div className="mt-4 max-w-[60ch] space-y-2">
        <Textarea
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="One sentence: what is this body of work for?"
          autoFocus
          disabled={busy}
          className="leading-relaxed"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              save();
            }
            if (e.key === "Escape") {
              setDraft(value);
              setEditing(false);
            }
          }}
        />
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={save} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Check />} Save
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setDraft(value);
              setEditing(false);
            }}
            disabled={busy}
          >
            <X /> Cancel
          </Button>
          {error && (
            <span className="font-mono text-xs text-proposed-foreground">
              {error}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="group mt-4 flex items-start gap-2">
      {value ? (
        <p className="leading-relaxed text-muted-foreground">{value}</p>
      ) : (
        <p className="leading-relaxed text-ink-faint italic">
          No intent yet — add one sentence on what this project is for.
        </p>
      )}
      <button
        type="button"
        onClick={() => {
          setDraft(value);
          setEditing(true);
        }}
        className="mt-1 shrink-0 rounded p-1 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-accent-deep focus-visible:opacity-100"
        aria-label="Edit intent"
        title="Edit intent"
      >
        <Pencil className="size-3.5" />
      </button>
    </div>
  );
}
