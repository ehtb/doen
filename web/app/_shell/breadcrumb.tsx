"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// A crumb in the persistent header's trail (after the Doen brand). The last crumb is the
// current page (rendered as text); earlier ones link back up the hierarchy.
export type Crumb = { label: string; href?: string };

type Ctx = { crumbs: Crumb[] | null; setCrumbs: (c: Crumb[] | null) => void };

const BreadcrumbContext = createContext<Ctx | null>(null);

export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<Crumb[] | null>(null);
  // setCrumbs is stable (useState); memoise the value so only a real crumb change re-renders
  // the header — and so SetBreadcrumb's effect doesn't loop on a fresh value object each render.
  const value = useMemo(() => ({ crumbs, setCrumbs }), [crumbs]);
  return <BreadcrumbContext.Provider value={value}>{children}</BreadcrumbContext.Provider>;
}

export function useBreadcrumb(): Crumb[] | null {
  return useContext(BreadcrumbContext)?.crumbs ?? null;
}

// A page declares its breadcrumb trail. Server pages pass data-only props down to this client
// component; it registers on mount and clears on unmount, so a route that declares no trail
// falls back to the path-derived structure the header computes.
export function SetBreadcrumb({ crumbs }: { crumbs: Crumb[] }) {
  const setCrumbs = useContext(BreadcrumbContext)?.setCrumbs;
  const key = JSON.stringify(crumbs);
  useEffect(() => {
    setCrumbs?.(JSON.parse(key) as Crumb[]);
    return () => setCrumbs?.(null);
  }, [setCrumbs, key]);
  return null;
}
