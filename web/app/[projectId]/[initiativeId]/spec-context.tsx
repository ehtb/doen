"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import type { Spec } from "@/lib/types";

type SpecContextValue = {
  spec: Spec;
  setSpec: (s: Spec) => void;
  busy: boolean;
  error: string | null;
  setError: (e: string | null) => void;
  mutate: (path: string, method: string, body: object) => Promise<boolean>;
  // Force an immediate SWR revalidation — call this after raw-fetch state transitions
  // (start-building, revert-to-draft) so the context updates without waiting for the poll.
  refreshSpec: () => Promise<void>;
  // 0013 u3: a one-shot hand-off from the document's kickoff surface to the rail.
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

const specFetcher = (url: string) => fetch(url, { cache: "no-store" }).then((r) => r.json());

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
  const router = useRouter();

  const specRef = useRef(spec);
  specRef.current = spec;

  const { data: freshSpec, mutate: revalidateSpec } = useSWR<Spec>(
    `/api/specs/${initialSpec.initiative_id}`,
    specFetcher,
    { refreshInterval: 5000, fallbackData: initialSpec, revalidateOnFocus: false, dedupingInterval: 4000 },
  );

  // State transitions (start-building, revert-to-draft) update doc.state via jsonb_set without
  // incrementing version — so we check for EITHER a newer version OR a state change at same version.
  function isNewer(incoming: Spec, current: Spec) {
    return incoming.version > current.version || incoming.state !== current.state;
  }

  // Sync from RSC-delivered prop after router.refresh() — useState ignores prop changes after mount.
  useEffect(() => {
    if (isNewer(initialSpec, specRef.current)) {
      setSpec(initialSpec);
    }
  }, [initialSpec]);

  // Apply external changes arriving via the SWR poll (MCP submissions, other sessions).
  useEffect(() => {
    if (!freshSpec || !isNewer(freshSpec, specRef.current)) return;
    setSpec(freshSpec);
    // Any state change needs an RSC re-render: CriteriaVerification and LearnStage render
    // conditionally per state, and the ConversationRail receives mode/intro as server props.
    if (freshSpec.state !== specRef.current.state) {
      router.refresh();
    }
  }, [freshSpec, router]);

  // Directly fetch and apply fresh spec — used after raw-fetch state transitions (start-building,
  // revert-to-draft) where the context must update in the same async tick, not after the SWR
  // effect cycle. Also primes the SWR cache so the next poll doesn't re-apply stale data.
  // No version guard here — it's explicitly called after a known state change.
  const refreshSpec = useCallback(async () => {
    try {
      const res = await fetch(`/api/specs/${initialSpec.initiative_id}`, { cache: "no-store" });
      if (!res.ok) return;
      const fresh: Spec = await res.json();
      if (fresh) {
        setSpec(fresh);
        revalidateSpec(fresh, { revalidate: false });
      }
    } catch {
      // Transient — fall back to the next SWR poll.
    }
  }, [initialSpec.initiative_id, revalidateSpec]);

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
      const updated: Spec = await res.json();
      setSpec(updated);
      // Any state change needs an RSC re-render for sections to appear/disappear.
      if (updated.state !== spec.state) {
        router.refresh();
      }
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
        refreshSpec,
        railPrompt,
        requestRailPrompt: setRailPrompt,
        clearRailPrompt: () => setRailPrompt(null),
      }}
    >
      {children}
    </SpecCtx.Provider>
  );
}
