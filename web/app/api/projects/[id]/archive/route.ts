import { NextResponse, type NextRequest } from "next/server";

// BD-11: proxy archive action to the backend.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/projects/${id}/archive`, {
    method: "POST",
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
