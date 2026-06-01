"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

// Projects are lightweight containers: a name + one-sentence intent, no AI shaping.
// The ID and prefix are both derived from the name server-side (BD-11).
export default function NewProject({
  defaultOpen = false,
}: {
  defaultOpen?: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(defaultOpen);
  const [name, setName] = useState("");
  const [intent, setIntent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setName("");
    setIntent("");
    setError(null);
  }

  async function create() {
    const n = name.trim();
    if (!n || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: n, intent: intent.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `couldn't create the project (${res.status})`);
      }
      reset();
      setOpen(false);
      router.refresh(); // the projects list re-renders with the new one — no full reload
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} className="shadow-sm">
        <Plus /> New project
      </Button>
    );
  }

  return (
    <form
      className="animate-rise space-y-3 rounded-lg border border-border bg-card/60 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        create();
      }}
    >
      <div className="space-y-1">
        <label className="font-mono text-[10.5px] tracking-widest text-ink-faint uppercase">
          Name
        </label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Build Doen"
          autoFocus
          disabled={busy}
        />
      </div>

      <div className="space-y-1">
        <label className="font-mono text-[10.5px] tracking-widest text-ink-faint uppercase">
          Intent
        </label>
        <Textarea
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="What is the intended perspective of the project?"
          rows={2}
          disabled={busy}
          className="text-[13px]"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={busy || name.trim().length === 0}>
          {busy && <Loader2 className="animate-spin" />}
          {busy ? "Creating…" : "Create project"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          disabled={busy}
        >
          Cancel
        </Button>
        {error && (
          <span className="font-mono text-xs text-proposed-foreground">
            {error}
          </span>
        )}
      </div>
    </form>
  );
}
