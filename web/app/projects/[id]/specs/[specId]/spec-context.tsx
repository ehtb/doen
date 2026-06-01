"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import type { Spec } from "@/lib/types";

// One shared spec for the whole spec page (0012 u3, a6). The document surface and the rail's
// guided review both read and write through this, so confirming or rejecting an item in the rail
// updates the document — and the progress indicator — in real time, with no reload. Every write
// goes through the optimistic lock at the version the page last saw.
type SpecContextValue = {
  spec: Spec;
  setSpec: (s: Spec) => void;
  busy: boolean;
  error: string | null;
  setError: (e: string | null) => void;
  mutate: (path: string, method: string, body: object) => Promise<boolean>;
  // 0013 u3: a one-shot hand-off from the document's kickoff surface to the rail. The kickoff
  // sets a prompt (a work-unit decomposition request); the rail picks it up, sends it to the
  // Advisor, and clears it — so the Advisor's suggestion appears in the rail, human-confirmed.
  railPrompt: string | null;
  requestRailPrompt: (text: string) => void;
  clearRailPrompt: () => void;
};

const SpecCtx = createContext<SpecContextValue | null>(null);

export function useSpec(): SpecContextValue {
  const ctx = useContext(SpecCtx);
  if (!ctx) throw new Error("useSpec must be used within a SpecProvider");
  return ctx;
}

// Like useSpec, but returns null outside a SpecProvider instead of throwing — the conversation
// rail is shared with the project dashboard, which has no spec context.
export function useSpecOptional(): SpecContextValue | null {
  return useContext(SpecCtx);
}

export function SpecProvider({
  initialSpec,
  children,
}: {
  initialSpec: Spec;
  children: ReactNode;
}) {
  const [spec, setSpec] = useState<Spec>(initialSpec);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [railPrompt, setRailPrompt] = useState<string | null>(null);

  async function mutate(path: string, method: string, body: object): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(path, {
        method,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...body, version: spec.version }),
      });
      if (res.status === 409) {
        setError("The spec changed elsewhere — reloading to catch up…");
        setTimeout(() => location.reload(), 900);
        return false;
      }
      if (!res.ok) {
        setError(`request failed (${res.status})`);
        return false;
      }
      setSpec(await res.json());
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <SpecCtx.Provider
      value={{
        spec,
        setSpec,
        busy,
        error,
        setError,
        mutate,
        railPrompt,
        requestRailPrompt: setRailPrompt,
        clearRailPrompt: () => setRailPrompt(null),
      }}
    >
      {children}
    </SpecCtx.Provider>
  );
}
