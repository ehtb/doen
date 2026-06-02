import { NextResponse, type NextRequest } from "next/server";

const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const status = req.nextUrl.searchParams.get("status");
  const url = status
    ? `${API_BASE}/projects/${id}/drift-reports?status=${encodeURIComponent(status)}`
    : `${API_BASE}/projects/${id}/drift-reports`;
  const res = await fetch(url, { cache: "no-store" });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
