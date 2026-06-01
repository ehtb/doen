import { NextResponse, type NextRequest } from "next/server";

// Same-origin proxy for the spec-authoring subtree (browser -> Next -> backend),
// so the backend stays CORS-free. Forwards by method + subpath:
//   POST  /api/specs/{id}/items                      -> add
//   POST  /api/specs/{id}/items/{itemId}/confirm     -> confirm
//   POST  /api/specs/{id}/items/{itemId}/retire      -> retire
//   PATCH /api/specs/{id}/items/{itemId}             -> edit
const API_BASE = process.env.DOEN_API_URL ?? "http://localhost:8000";

async function forward(
  req: NextRequest,
  params: Promise<{ id: string; seg?: string[] }>,
  method: "POST" | "PATCH",
) {
  const { id, seg } = await params;
  const sub = seg?.length ? "/" + seg.join("/") : "";
  const res = await fetch(`${API_BASE}/specs/${id}/items${sub}`, {
    method,
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": "application/json" },
  });
}

export function POST(req: NextRequest, ctx: { params: Promise<{ id: string; seg?: string[] }> }) {
  return forward(req, ctx.params, "POST");
}

export function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string; seg?: string[] }> }) {
  return forward(req, ctx.params, "PATCH");
}
