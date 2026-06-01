import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// What the Advisor is doing in each lifecycle state — the rail's header mode (0009 u3, 0011).
// Lives here (not in the client rail) so server components can resolve it too.
const STATE_MODE: Record<string, string> = {
  draft: "shaping the spec",
  building: "guiding the build",
  learning: "drawing out the learnings",
  complete: "drawing out the learnings",
};

export function stateMode(state: string): string {
  return STATE_MODE[state] ?? "thinking with you";
}

// 0012 u5: the short id (BD-7) + URL slug (bd-7-csv-export) from a project prefix + per-project
// seq. `slugify` mirrors the backend (models.slugify) so a dashboard link lands on the canonical
// URL without a redirect bounce; resolution itself only needs the prefix + number.
export function slugify(title: string | null | undefined): string {
  const s = (title ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || "initiative";
}

// 0013 u2: preview the short handle a new project will get from its name (mirrors the backend
// models.derive_prefix), so the creation form can show 'Build Doen' -> 'BD' as the user types.
export function derivePrefix(name: string): string {
  const words = name.match(/[A-Za-z0-9]+/g) ?? [];
  const first = words[0];
  if (!first) return "P";
  const initials = words.map((w) => w[0]).join("").toUpperCase();
  return (initials.length >= 2 ? initials : first.slice(0, 2).toUpperCase()) || "P";
}

export function shortId(prefix: string, seq: number): string {
  return `${prefix}-${seq}`;
}

