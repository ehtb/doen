"use client";

import { useState } from "react";
import { Check, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";

// A copyable prompt for an external Claude Code session that audits the three constitution
// docs for drift against the current codebase. The prompt is self-contained — it points at
// the /sync-docs skill but also restates the procedure so it works without the skill being
// loaded. Mirrors CopyBuildPrompt's button shape (BD-14 u4).
export default function CopySyncDocsPrompt() {
  const [copied, setCopied] = useState(false);

  const prompt = `Audit Doen's three constitution docs for drift against the current codebase.

Run the /sync-docs skill in this repo (.claude/skills/sync-docs/SKILL.md). It documents the procedure; the short version:

1. Read the three docs:
   - agents.md (the constitution; must stay under ~200 lines)
   - docs/spec-contract.md (the Pydantic shapes + MCP tool surface)
   - docs/design-principles.md (rationale + append-only rejected directions)
2. Compare against current reality:
   - backend/app/models.py (domain model + derive_state())
   - backend/app/mcp_server.py (the @mcp.tool() functions, in order)
   - backend/app/routers/ (HTTP routes per domain)
   - backend/migrations/ (newest tables/columns)
   - completed specs since the last-reviewed header in agents.md
3. Identify drift in three shapes: stale concepts (renamed fields, removed tools, replaced lifecycles), missing additions (new tools / fields / tables / principles), aspirational fiction (docs describe something the code doesn't do).
4. SURFACE a numbered audit for my confirmation BEFORE writing — do not touch any doc until I approve. After my confirmation, write the changes and bump the last-reviewed: header in agents.md to today's date and the most recent spec.

Hard rules: rejected directions in design-principles.md are append-only; agents.md stays under ~200 lines; no doc edit before my confirmation.`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked */
    }
  }

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={copy}
      title="Copy a prompt that audits the three constitution docs against the codebase"
      className="h-7 px-2.5 font-mono text-[11px] tracking-wide"
    >
      {copied ? <Check /> : <FileText />} {copied ? "Copied" : "Copy /sync-docs prompt"}
    </Button>
  );
}
