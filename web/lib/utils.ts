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
  complete: "drawing out the learnings",
};

export function stateMode(state: string): string {
  return STATE_MODE[state] ?? "thinking with you";
}
