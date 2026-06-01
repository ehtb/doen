"use client";

import { useState } from "react";
import { Check, Copy, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function OnboardingHint({
  projectId,
  prompt,
  initialDismissed,
}: {
  projectId: string;
  prompt: string;
  initialDismissed: boolean;
}) {
  const [dismissed, setDismissed] = useState(initialDismissed);
  const [copied, setCopied] = useState(false);
  const [dismissing, setDismissing] = useState(false);

  if (dismissed) return null;

  async function copyPrompt() {
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function dismiss() {
    if (dismissing) return;
    setDismissing(true);
    try {
      await fetch(`/api/projects/${projectId}/onboarding/dismiss`, { method: "POST" });
      setDismissed(true);
    } finally {
      setDismissing(false);
    }
  }

  return (
    <div className="animate-rise mb-6 flex flex-wrap items-center gap-4 rounded-xl border border-primary/30 bg-primary/4 px-4 py-3.5">
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[10.5px] font-semibold tracking-widest text-accent-deep uppercase">
          Set up your executor
        </p>
        <p className="text-[13.5px] leading-relaxed text-foreground">
          Paste this into Claude Code (or any MCP-connected executor) to install
          the Doen configuration files into your project directory.
        </p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={copyPrompt} className="shadow-sm">
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
        <Button
          size="sm"
          variant="ghost"
          onClick={dismiss}
          disabled={dismissing}
          className="text-ink-faint hover:text-foreground"
          aria-label="Dismiss onboarding hint"
        >
          <X className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}
