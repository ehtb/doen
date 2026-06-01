"use client";

import { useState } from "react";
import { Check, Terminal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

// A copyable prompt for an external Claude Code session, always available — not only in the
// kickoff's no-units moment. Covers both paths: propose a decomposition when there are no
// units, claim and build a ready one when there are. The kickoff's own prompt stays
// decomposition-focused for the pre-build moment where it lives.
export default function CopyBuildPrompt() {
  const { spec } = useSpec();
  const [copied, setCopied] = useState(false);

  const heading = spec.short_id
    ? `${spec.short_id} (${spec.initiative_id})`
    : spec.initiative_id;
  const prompt = `Build the Doen initiative ${heading}.

Connect to the Doen MCP server, then:
1. Call get_spec(initiative_id="${spec.initiative_id}") and get_conversation_summary(initiative_id="${spec.initiative_id}") to ground yourself in intent, constraints, discretion, acceptance — and the reasoning behind them (resolved decisions, rejected alternatives, the human's stated priorities).
2. Call list_units(spec_id="${spec.initiative_id}"). If there are READY units, claim_unit one, call get_guidance for it, build it (report_progress as you go), then submit_for_verification with criteria_results — and stop for my verdict before the next. If there are NO units yet, propose a decomposition via propose_unit per slice, naming the acceptance criteria each unit satisfies. Stop after proposing; I'll confirm in Doen before you build.
3. You cannot confirm your own unit or approve your own submission — those are mine. If you hit a call outside the spec's constraints + discretion, raise_decision; don't guess.`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked — copy via the kickoff's pre block instead, if visible */
    }
  }

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={copy}
      title="Copy a prompt to paste into Claude Code"
      className="h-7 px-2.5 font-mono text-[11px] tracking-wide"
    >
      {copied ? <Check /> : <Terminal />} {copied ? "Copied" : "Copy build prompt"}
    </Button>
  );
}
