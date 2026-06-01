"use client";

import { useState } from "react";
import { Check, Copy, Sparkles, Terminal } from "lucide-react";

import type { SpecItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { useSpec } from "./spec-context";

const DECOMP_REQUEST =
  "Propose a work-unit decomposition for this spec — break the work into units, each naming the acceptance criteria it satisfies. I'll confirm them before anything is built.";

const confirmed = (items: SpecItem[]) => items.filter((i) => i.status === "confirmed");

// The implementation kickoff (0013 u3): shown in place of the passive "no work units yet" empty
// state once a spec is fully reviewed. It bridges spec -> build with (1) a summary of what's
// confirmed, (2) a copyable, functional Claude Code prompt that reads this spec over MCP and
// proposes units, and (3) an action to have the Advisor suggest the decomposition in the rail.
export default function KickoffSurface() {
  const { spec, requestRailPrompt } = useSpec();
  const [copied, setCopied] = useState(false);

  const cCount = confirmed(spec.constraints).length;
  const dCount = confirmed(spec.discretion).length;
  const aCrit = confirmed(spec.acceptance);

  const heading = spec.short_id
    ? `${spec.short_id} (${spec.initiative_id})`
    : spec.initiative_id;
  const prompt = `Build the Doen initiative ${heading}.

Connect to the Doen MCP server, then:
1. Call get_spec(initiative_id="${spec.initiative_id}") and ground yourself in its intent, constraints, discretion, and acceptance criteria.
2. Propose a work-unit decomposition: for each coherent slice of the work, call propose_unit(spec_id="${spec.initiative_id}", title=…, scope=…, criterion_ids=[…]) naming the acceptance criteria it satisfies. Units are created "proposed" — I confirm each one in Doen before you build it; you cannot confirm your own unit.
3. Stop after proposing. I'll review and confirm, then you claim_unit and build.`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked — the prompt is still selectable in the block below */
    }
  }

  return (
    <section className="animate-rise mt-4 overflow-hidden rounded-xl border border-primary/30 bg-card/70">
      <div className="border-b border-border bg-primary/5 px-5 py-4">
        <h3 className="font-serif text-[18px] leading-snug">Ready to build</h3>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
          The spec is reviewed — hand it to an executor. It decomposes the work into units you
          confirm here before anything is built.
        </p>
      </div>

      <div className="space-y-5 px-5 py-5">
        {/* (1) what's confirmed — the build targets */}
        <div>
          <p className="font-mono text-[10.5px] tracking-widest text-ink-faint uppercase">
            Confirmed spec
          </p>
          <p className="mt-1.5 text-[13px] text-foreground">
            <span className="text-accent-deep">{cCount}</span> constraint{cCount === 1 ? "" : "s"}{" "}
            · <span className="text-accent-deep">{dCount}</span> latitude
            {dCount === 1 ? "" : "s"} ·{" "}
            <span className="text-accent-deep">{aCrit.length}</span> acceptance criteri
            {aCrit.length === 1 ? "on" : "a"} — all confirmed.
          </p>
          {aCrit.length > 0 && (
            <ul className="mt-2.5 space-y-1.5">
              {aCrit.map((c) => (
                <li key={c.id} className="flex items-start gap-2 text-[12.5px] leading-snug text-muted-foreground">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-confirmed" />
                  {c.text}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* (2) the functional MCP bridge — copy into Claude Code */}
        <div>
          <div className="flex items-center justify-between gap-3">
            <p className="flex items-center gap-1.5 font-mono text-[10.5px] tracking-widest text-ink-faint uppercase">
              <Terminal className="size-3.5" /> Kick off in Claude Code
            </p>
            <Button size="sm" variant="outline" onClick={copy} className="h-7 px-2.5 text-xs">
              {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy prompt"}
            </Button>
          </div>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-border bg-secondary/60 p-3.5 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-foreground">
            {prompt}
          </pre>
          <p className="mt-1.5 font-mono text-[10px] leading-relaxed text-ink-faint">
            Requires the Doen MCP server connected — this repo&apos;s{" "}
            <code className="text-ink-soft">.mcp.json</code> configures it. The executor calls{" "}
            <code className="text-ink-soft">get_spec</code> +{" "}
            <code className="text-ink-soft">propose_unit</code>; the proposed units land here for
            you to confirm.
          </p>
        </div>

        {/* (3) or have the Advisor suggest the decomposition in the rail */}
        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
          <Button
            variant="secondary"
            onClick={() => requestRailPrompt(DECOMP_REQUEST)}
            className="shadow-sm"
          >
            <Sparkles /> Ask the Advisor to decompose
          </Button>
          <span className="font-mono text-[10.5px] leading-relaxed text-ink-faint">
            the Advisor suggests a breakdown in the rail — you decide, then it&apos;s built
          </span>
        </div>
      </div>
    </section>
  );
}
