"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, Check, Copy, Hammer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

function buildMcpPrompt(initiativeId: string, title: string) {
  return `Build initiative ${initiativeId} — ${title}.

Call get_spec("${initiativeId}") and get_conversation_summary("${initiativeId}") to ground yourself in the spec and its resolved decisions. Then follow the spec-contract: claim units, build against confirmed items only, escalate decisions with raise_decision, submit_for_verification when done.`;
}

function buildPlanPrompt(initiativeId: string, title: string) {
  return `Plan the build for initiative ${initiativeId} — ${title}.

Call get_spec("${initiativeId}") and get_conversation_summary("${initiativeId}") to ground yourself in the spec and its resolved decisions. Lay out a step-by-step build plan — one step per work unit — covering what you'll build, in what order, and which decisions you might need to raise. Do NOT start building yet. Present the plan for review first.`;
}

export default function NextStepHint() {
  const { spec, refreshSpec } = useSpec();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [copiedKey, setCopiedKey] = useState<"execute" | "plan" | null>(null);

  const executePrompt = buildMcpPrompt(spec.initiative_id, spec.title);
  const planPrompt = buildPlanPrompt(spec.initiative_id, spec.title);

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
      await refreshSpec();
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function copyPrompt(key: "execute" | "plan") {
    const text = key === "execute" ? executePrompt : planPrompt;
    await navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  }

  if (spec.state === "learning") {
    return (
      <div className="animate-rise mt-5 flex flex-wrap items-center gap-4 rounded-xl border border-confirmed/30 bg-confirmed/4 px-4 py-3.5">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10.5px] font-semibold tracking-widest text-confirmed-foreground uppercase">
            All criteria verified
          </p>
          <p className="text-[13.5px] leading-relaxed text-foreground">
            Write the retrospective below to close out this initiative and feed
            its learnings back to the flywheel.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="shadow-sm"
          onClick={() =>
            document
              .getElementById("learn")
              ?.scrollIntoView({ behavior: "smooth" })
          }
        >
          <ArrowDown className="size-3.5" /> Write retrospective
        </Button>
      </div>
    );
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
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => copyPrompt("plan")}
            className="shadow-sm"
          >
            {copiedKey === "plan" ? (
              <>
                <Check className="size-3.5" /> Copied
              </>
            ) : (
              <>
                <Copy className="size-3.5" /> Plan first
              </>
            )}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => copyPrompt("execute")}
            className="shadow-sm"
          >
            {copiedKey === "execute" ? (
              <>
                <Check className="size-3.5" /> Copied
              </>
            ) : (
              <>
                <Copy className="size-3.5" /> Execute
              </>
            )}
          </Button>
        </div>
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
