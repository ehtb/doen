import type { Initiative, Project, ProjectDashboard, Spec } from "./types";

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

export async function listInitiatives(): Promise<Initiative[]> {
  // The dashboard's feed — initiatives change as they're created/advanced, so no cache.
  const res = await fetch(`${API_BASE}/initiatives`, { cache: "no-store" });
  if (!res.ok) throw new Error(`initiatives fetch failed (${res.status})`);
  return res.json();
}

export async function listProjects(): Promise<Project[]> {
  // The level above the dashboard (0010) — created out of band, so never cache.
  const res = await fetch(`${API_BASE}/projects`, { cache: "no-store" });
  if (!res.ok) throw new Error(`projects fetch failed (${res.status})`);
  return res.json();
}

export async function getProjectDashboard(
  projectId: string,
): Promise<ProjectDashboard | null> {
  // The project as a whole — its grouped initiatives change live, so no cache.
  const res = await fetch(`${API_BASE}/projects/${projectId}/dashboard`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`project dashboard fetch failed (${res.status})`);
  return res.json();
}
