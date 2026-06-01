"use client";

import { useState } from "react";
import { Check, Loader2, Pencil, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useSpec } from "./spec-context";

// Inline intent editing on the initiative page, restricted to the draft phase — once the spec
// moves to building, the intent is the contract the build runs against and should not shift.
// PUTs the full spec; the SpecProvider's mutate carries the current `version`, so a concurrent
// change is caught (409 -> reload) instead of silently clobbered.
export default function SpecIntent() {
  const { spec, busy, mutate } = useSpec();
  const editable = spec.state === "draft";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(spec.intent);

  async function save() {
    if (busy) return;
    const ok = await mutate(`/api/specs/${spec.initiative_id}`, "PUT", {
      ...spec,
      intent: draft.trim(),
    });
    if (ok) setEditing(false);
  }

  if (editing && editable) {
    return (
      <div className="mt-2.5 space-y-2">
        <Textarea
          rows={4}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Why are we doing this? What problem does it solve, for whom?"
          autoFocus
          disabled={busy}
          className="bg-card font-serif text-lg leading-relaxed"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              save();
            }
            if (e.key === "Escape") {
              setDraft(spec.intent);
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
              setDraft(spec.intent);
              setEditing(false);
            }}
            disabled={busy}
          >
            <X /> Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="group mt-2.5 flex items-start gap-2">
      <p className="font-serif text-lg leading-relaxed whitespace-pre-wrap">
        {spec.intent || (
          <span className="text-ink-faint italic">
            No intent yet — describe why this initiative exists.
          </span>
        )}
      </p>
      {editable && (
        <button
          type="button"
          onClick={() => {
            setDraft(spec.intent);
            setEditing(true);
          }}
          className="mt-2 shrink-0 rounded p-1 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-accent-deep focus-visible:opacity-100"
          aria-label="Edit intent"
          title="Edit intent"
        >
          <Pencil className="size-3.5" />
        </button>
      )}
    </div>
  );
}
