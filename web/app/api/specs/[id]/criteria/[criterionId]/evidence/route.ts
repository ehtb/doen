import { NextResponse, type NextRequest } from "next/server";

const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string; criterionId: string }> },
) {
  const { id, criterionId } = await params;
  const res = await fetch(
    `${API_BASE}/specs/${id}/criteria/${criterionId}/evidence`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await req.text(),
      cache: "no-store",
    },
  );
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}
