import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy (browser -> Next -> backend) for a spec's work units, keeping
// the backend CORS-free. Mirrors lib/api.ts and the decisions proxy.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const status = req.nextUrl.searchParams.get("status");
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await fetch(`${API_BASE}/specs/${id}/units${qs}`, { cache: "no-store" });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
