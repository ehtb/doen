import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy: a rail turn (browser) POSTs here; Next forwards to the FastAPI
// backend, which persists the human message, generates the Advisor's reply, and returns
// both. An LLM failure surfaces as the backend's 502, passed straight through.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/initiatives/${id}/advisor`, {
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
