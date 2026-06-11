"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";

// A copyable prompt for an external Claude Code session that audits core documentation
// docs for drift against the current codebase. The prompt is self-contained — it points at
// the /sync-docs skill but also restates the procedure so it works without the skill being
// loaded. Mirrors CopyBuildPrompt's button shape (BD-14 u4).
export default function CopySyncDocsPrompt() {
  const [copied, setCopied] = useState(false);

  const prompt = `Audit the project's core documentation (constitution) for drift against the current codebase.

Run the /sync-docs skill in this repo (.claude/skills/sync-docs/SKILL.md). It documents the procedure; the short version:

1. Identify and read core docs (e.g., agents.md, contract specs, design principles).
2. Compare against current reality in the codebase (models, interfaces, migrations, and recent work).
3. Identify drift: stale concepts (renamed/removed), missing additions (new features/models), or aspirational fiction (docs describe what isn't there).
4. SURFACE a numbered audit for my confirmation BEFORE writing — do not touch any doc until I approve. After confirmation, write changes and update any "last-reviewed" headers.

Hard rules: preserve append-only sections; respect doc size constraints; no doc edit before my confirmation.`;

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
      size="xs"
      variant="outline"
      shadow="none"
      onClick={copy}
      title="Copy a prompt that audits core documentation against the codebase"
    >
      {copied ? <Check /> : <Copy />}{" "}
      {copied ? "Copied" : "Copy /sync-docs prompt"}
    </Button>
  );
}
