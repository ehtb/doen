"use client";

import { useState } from "react";
import { Check, Loader2, Sparkles, X } from "lucide-react";
import type { AcceptanceCriterion, SpecItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useSpec } from "./spec-context";

// 0012 u3 (a5/a6/a8): the Advisor walks the human through the proposed spec one item at a time,
// in the rail, in the guided order — constraints, then acceptance criteria, then agent latitude.
// Each action writes through the shared spec, so the document and the progress bar build up live
// as items are confirmed. Rejecting removes the item and (server-side) logs it to this thread.
const ORDER = ["constraints", "acceptance", "discretion"] as const;
type ReviewSection = (typeof ORDER)[number];

const LABEL: Record<ReviewSection, string> = {
  constraints: "constraint",
  acceptance: "acceptance criterion",
  discretion: "agent-latitude item",
};

export default function GuidedReview() {
  const { spec, busy, mutate } = useSpec();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const queue: { section: ReviewSection; it: SpecItem }[] = ORDER.flatMap(
    (section) =>
      (spec[section] as SpecItem[])
        .filter((i) => i.status === "proposed")
        .map((it) => ({ section, it })),
  );
  const reviewable = [
    ...spec.constraints,
    ...spec.acceptance,
    ...spec.discretion,
  ].filter((i) => i.status !== "retired");
  const confirmed = reviewable.filter((i) => i.status === "confirmed").length;

  // Nothing to walk: a spec with no items at all shows nothing; once items exist and all are
  // reviewed, close the loop with a clear "done" so the human knows the spec is theirs.
  if (queue.length === 0) {
    if (reviewable.length === 0) return null;
    return (
      <div className="rounded-xl border border-confirmed/40 bg-confirmed/[0.08] p-3.5">
        <div className="flex items-center gap-1.5 font-mono text-[10px] tracking-[0.13em] text-confirmed uppercase">
          <Check className="size-3" /> review complete
        </div>
        <p className="mt-1.5 text-[13px] leading-snug text-rail-foreground">
          That&apos;s the spec — every item reviewed. It&apos;s yours now; ask
          me anything or start shaping the work.
        </p>
      </div>
    );
  }

  const { section, it } = queue[0];
  const iid = spec.initiative_id;
  const verify =
    section === "acceptance" ? (it as AcceptanceCriterion).verify : null;

  const confirm = () =>
    mutate(`/api/specs/${iid}/items/${it.id}/confirm`, "POST", {});
  const reject = () =>
    mutate(`/api/specs/${iid}/items/${it.id}/reject`, "POST", {});
  const confirmLatitude = () =>
    mutate(`/api/specs/${iid}/confirm-all`, "POST", { section: "discretion" });
  async function saveEdit() {
    if (!draft.trim()) return;
    if (
      await mutate(`/api/specs/${iid}/items/${it.id}`, "PATCH", { text: draft })
    ) {
      setEditing(false);
      setDraft("");
    }
  }

  return (
    <div className="rounded-xl border border-primary/40 bg-rail-card p-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-[0.13em] text-primary uppercase">
          <Sparkles className="size-3" /> guided review
        </span>
        <span className="font-mono text-[10px] tabular-nums text-rail-muted">
          {confirmed} confirmed · {queue.length} to go
        </span>
      </div>
      <p className="mt-1.5 text-[13px] leading-snug text-rail-muted">
        Let&apos;s go through the spec together — accept what&apos;s right,
        reject what isn&apos;t, or edit the wording. This is the{" "}
        {LABEL[section]} I&apos;d look at next.
      </p>

      <div className="mt-2.5 rounded-lg border border-rail-border bg-rail p-3">
        <div className="mb-1.5 font-mono text-[9.5px] tracking-[0.1em] text-rail-muted uppercase">
          proposed {LABEL[section]}
        </div>
        {editing ? (
          <div className="space-y-2">
            <Textarea
              autoFocus
              rows={3}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="resize-none border-rail-border bg-rail-card text-[13px] text-rail-foreground"
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={busy}
                onClick={saveEdit}
                className="h-7 px-2.5 text-xs"
              >
                {busy ? <Loader2 className="animate-spin" /> : <Check />} Save
                wording
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setEditing(false);
                  setDraft("");
                }}
                className="h-7 px-2.5 text-xs text-rail-foreground hover:bg-black/5"
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-[13px] leading-snug text-rail-foreground">
            {it.text}
          </p>
        )}
        {verify && !editing && (
          <p className="mt-1.5 font-mono text-[10px] text-rail-muted">
            verify: {verify.kind} — {verify.detail}
          </p>
        )}
      </div>

      {!editing && (
        <>
          <div className="mt-3 flex items-center gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={confirm}
              className="h-7 bg-confirmed px-2.5 text-xs text-white hover:bg-confirmed/90"
            >
              {busy ? <Loader2 className="animate-spin" /> : <Check />} Accept
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={reject}
              className="h-7 border border-rail-border px-2.5 text-xs text-rail-foreground hover:bg-black/5"
            >
              <X /> Reject
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setEditing(true);
                setDraft(it.text);
              }}
              className="h-7 px-2 text-xs text-rail-muted hover:bg-black/5 hover:text-rail-foreground"
            >
              Edit
            </Button>
          </div>
          {section === "discretion" && (
            // D2 -> c: latitude is the executor's call — let the human clear it in one gesture.
            <button
              type="button"
              disabled={busy}
              onClick={confirmLatitude}
              className="mt-2 font-mono text-[10.5px] tracking-wide text-rail-muted underline-offset-4 hover:text-primary hover:underline disabled:opacity-50"
            >
              confirm all remaining latitude at once
            </button>
          )}
        </>
      )}
    </div>
  );
}
