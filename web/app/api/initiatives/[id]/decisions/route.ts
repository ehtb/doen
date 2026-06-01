import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy: the browser (the rail) talks to Next; Next talks to the
// FastAPI backend. Keeps the backend free of browser/CORS concerns and matches
// the server-side fetch pattern in lib/api.ts.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/initiatives/${id}/decisions`, {
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
