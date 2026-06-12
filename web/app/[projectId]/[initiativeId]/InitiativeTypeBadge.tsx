"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FlaskConical, Wrench } from "lucide-react";
import { useSpec } from "./spec-context";

export default function InitiativeTypeBadge() {
  const { spec, refreshSpec } = useSpec();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const isDraft = spec.state === "draft";
  const isResearch = spec.initiative_type === "research";

  async function toggle() {
    if (!isDraft || busy) return;
    setBusy(true);
    try {
      const newType = isResearch ? "engineering" : "research";
      const res = await fetch(`/api/initiatives/${spec.initiative_id}/type`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ initiative_type: newType }),
      });
      if (!res.ok) return;
      await refreshSpec();
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  const badge = isResearch ? (
    <span className="flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-widest uppercase bg-confirmed/15 text-confirmed-foreground">
      <FlaskConical className="size-2.5" /> Research
    </span>
  ) : (
    <span className="flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-widest uppercase bg-primary/10 text-accent-deep">
      <Wrench className="size-2.5" /> Engineering
    </span>
  );

  if (!isDraft) return badge;

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      title={`Switch to ${isResearch ? "engineering" : "research"}`}
      className="cursor-pointer opacity-100 transition-opacity hover:opacity-70 disabled:opacity-40"
    >
      {badge}
    </button>
  );
}
