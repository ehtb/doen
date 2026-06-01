import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy: the project rail (browser) reads its conversation history through Next,
// which talks to the FastAPI backend (0010 u5). Mirrors the initiative messages proxy.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/projects/${id}/messages`, {
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
