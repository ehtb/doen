import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy for the human unit actions (browser -> Next -> backend):
//   POST /api/units/{id}/confirm  -> confirm a proposed unit
//   POST /api/units/{id}/verdict  -> record a verdict (approve / request changes)
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string; action: string }> },
) {
  const { id, action } = await params;
  const res = await fetch(`${API_BASE}/units/${id}/${action}`, {
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
