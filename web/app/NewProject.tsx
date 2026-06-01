"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { derivePrefix } from "@/lib/utils";

// Projects are lightweight containers (0013 u2 / constraint d8b2): a name + one-sentence intent,
// no AI shaping. The short prefix is auto-derived from the name (Build Doen -> BD) and editable
// before saving. On create the list re-renders in place — no full-page reload.
export default function NewProject({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const router = useRouter();
  const [open, setOpen] = useState(defaultOpen);
  const [name, setName] = useState("");
  const [intent, setIntent] = useState("");
  const [prefix, setPrefix] = useState("");
  const [prefixTouched, setPrefixTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // until the user edits it themselves, the prefix tracks the name
  const shownPrefix = prefixTouched ? prefix : derivePrefix(name);

  function reset() {
    setName("");
    setIntent("");
    setPrefix("");
    setPrefixTouched(false);
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
        body: JSON.stringify({
          name: n,
          intent: intent.trim(),
          prefix: shownPrefix.trim() || null,
        }),
      });
      if (!res.ok) throw new Error(`couldn't create the project (${res.status})`);
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
      <div className="flex flex-wrap gap-3">
        <div className="min-w-48 flex-1 space-y-1">
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
        <div className="w-28 space-y-1">
          <label className="font-mono text-[10.5px] tracking-widest text-ink-faint uppercase">
            Prefix
          </label>
          <Input
            value={shownPrefix}
            onChange={(e) => {
              setPrefixTouched(true);
              setPrefix(e.target.value);
            }}
            placeholder="BD"
            disabled={busy}
            className="font-mono uppercase"
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="font-mono text-[10.5px] tracking-widest text-ink-faint uppercase">
          Intent
        </label>
        <Textarea
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="One sentence: what is this body of work for?"
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
        {error ? (
          <span className="font-mono text-xs text-proposed-foreground">{error}</span>
        ) : (
          <span className="ml-auto font-mono text-[10.5px] text-ink-faint">
            initiatives here will be{" "}
            <span className="text-accent-deep">{shownPrefix || "—"}-1</span>,{" "}
            {shownPrefix || "—"}-2 …
          </span>
        )}
      </div>
    </form>
  );
}
