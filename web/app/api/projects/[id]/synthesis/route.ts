import { NextResponse } from "next/server";

// Same-origin proxy so the client-side ProjectSynthesis component can fetch without exposing
// DOEN_API_URL. BD-20: proactive advisor observations + 'what we know' synthesis from project memory.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/projects/${id}/synthesis`, { cache: "no-store" });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
