import { NextResponse } from "next/server";

// BD-24: proxy to reject (dismiss) an observation without creating an initiative.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/observations/${id}/reject`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
