import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// What the Advisor is doing at each lifecycle stage — the rail's header mode (0009 u3).
// Lives here (not in the client rail) so server components can resolve it too.
const STAGE_MODE: Record<string, string> = {
  discover: "framing the problem",
  shape: "shaping the spec",
  bet: "weighing the bet",
  decompose: "decomposing the work",
  implement: "guiding the build",
  verify: "reviewing evidence",
  learn: "drafting the outcome",
};

export function stageMode(stage: string): string {
  return STAGE_MODE[stage] ?? "thinking with you";
}
