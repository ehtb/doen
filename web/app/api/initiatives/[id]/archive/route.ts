import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy for the soft-archive action (0013 follow-up). Reject (from draft) and
// Archive (from building/complete) share this endpoint — the reason field carries the label.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/initiatives/${id}/archive`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
