import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy for reading the living spec from the browser (the rail fetches the
// current version before accepting a proposal card, so the optimistic-lock write is fresh).
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/specs/${id}`, { cache: "no-store" });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
