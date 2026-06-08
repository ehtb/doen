import { NextResponse } from "next/server";

// BD-22: proxy to resolve an observation after initiative creation.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await req.text();
  const res = await fetch(`${API_BASE}/observations/${id}/resolve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
