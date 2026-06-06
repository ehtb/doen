"use client";

import { useSpec } from "./spec-context";

// Renders the initiative title from live spec state so it updates immediately when background
// shaping completes — without waiting for the RSC router.refresh() round-trip to finish.
export default function SpecTitle({ fallback }: { fallback: string }) {
  const { spec } = useSpec();
  return <>{spec.title || fallback}</>;
}
