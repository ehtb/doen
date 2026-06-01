import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy (browser -> Next -> backend) for description-first creation (0011 a3):
// the Advisor shapes the description into a full proposed spec and scaffolds the initiative.
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${API_BASE}/projects/${id}/initiatives/shape`, {
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
