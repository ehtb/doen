import type { Spec } from "./types";

// Server-side fetch target. In dev the Next server (Node) talks to the FastAPI
// backend directly; override with DOEN_API_URL when they live elsewhere.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function getSpec(initiativeId: string): Promise<Spec | null> {
  // The spec is a living document — never serve a stale render.
  const res = await fetch(`${API_BASE}/specs/${initiativeId}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`spec fetch failed (${res.status})`);
  return res.json();
}
