"use client";

import { useState } from "react";
import { Check, Copy, Hammer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

function buildMcpPrompt(initiativeId: string, title: string) {
  return `Build initiative ${initiativeId} — ${title}.

Call get_spec("${initiativeId}") and get_conversation_summary("${initiativeId}") to ground yourself in the spec and its resolved decisions. Then follow the spec-contract: claim units, build against confirmed items only, escalate decisions with raise_decision, submit_for_verification when done.`;
}

export default function NextStepHint() {
  const { spec } = useSpec();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const prompt = buildMcpPrompt(spec.initiative_id, spec.title);

  const items = [...spec.constraints, ...spec.discretion, ...spec.acceptance];
  const fullyReviewed =
    items.length > 0 &&
    !items.some((i) => i.status === "proposed") &&
    items.some((i) => i.status === "confirmed");

  async function startBuilding() {
    if (busy) return;
    setBusy(true);
    try {
      await fetch(`/api/initiatives/${spec.initiative_id}/start-building`, {
        method: "POST",
      });
    } finally {
      setBusy(false);
    }
  }

  async function copyPrompt() {
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (spec.state === "building") {
    return (
      <div className="animate-rise mt-5 flex flex-wrap items-center gap-4 rounded-xl border border-primary/30 bg-primary/4 px-4 py-3.5">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10.5px] font-semibold tracking-widest text-accent-deep uppercase">
            MCP prompt — paste into your agent
          </p>
          <p className="text-[13.5px] leading-relaxed text-foreground">
            Give this to Claude Code (or any MCP-connected executor) to start
            building.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={copyPrompt}
          className="shadow-sm"
        >
          {copied ? (
            <>
              <Check className="size-3.5" /> Copied
            </>
          ) : (
            <>
              <Copy className="size-3.5" /> Copy prompt
            </>
          )}
        </Button>
      </div>
    );
  }

  if (spec.state !== "draft" || !fullyReviewed) return null;

  return (
    <div className="animate-rise mt-5 flex flex-wrap items-center gap-4 rounded-xl border border-primary/30 bg-primary/4 px-4 py-3.5">
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[10.5px] font-semibold tracking-widest text-accent-deep uppercase">
          Ready to build
        </p>
        <p className="text-[13.5px] leading-relaxed text-foreground">
          Spec is fully reviewed. The Advisor will move to building mode when
          you start — or it transitions automatically when evidence is
          submitted.
        </p>
      </div>
      <Button
        size="sm"
        disabled={busy}
        onClick={startBuilding}
        className="shadow-sm"
      >
        <Hammer className="size-3.5" /> Start building
      </Button>
    </div>
  );
}
