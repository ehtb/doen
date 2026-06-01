import { NextResponse, type NextRequest } from "next/server";

// BD-9: proxy for onboarding status and dismissal. GET reads current state;
// POST /dismiss and POST /reset mutate it (persisted server-side per item_b8b031fbfe0f).
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/projects/${id}/onboarding`, { cache: "no-store" });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
