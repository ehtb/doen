"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function NewInitiative() {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function create() {
    const t = title.trim();
    if (!t || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/initiatives", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: t }),
      });
      if (!res.ok) throw new Error(`couldn't create (${res.status})`);
      const init = await res.json();
      // land straight in the new (empty) spec to start shaping it
      router.push(`/specs/${init.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <form
      className="mt-6 flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        create();
      }}
    >
      <Input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Name a new initiative…"
        className="max-w-sm"
        disabled={busy}
      />
      <Button type="submit" disabled={busy || title.trim().length === 0}>
        <Plus /> {busy ? "Creating…" : "New initiative"}
      </Button>
      {error && <span className="self-center font-mono text-xs text-proposed-foreground">{error}</span>}
    </form>
  );
}
