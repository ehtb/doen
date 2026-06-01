"""Doen MCP server — the executor-facing seam, over stdio.

Decision 1 in spec 0001 chose stdio for local dogfooding and the OSS self-hosted
path: auth lives outside the protocol (local subprocess + env credentials), so no
OAuth resource server is needed. Run it as its own process — it owns its own
Postgres pool and Redis client and talks to the store directly, NOT through the
FastAPI app:

    python -m app.mcp_server

Exposes exactly the four tools spec 0001/a4 calls for: get_spec, raise_decision,
resolve_decision, and wait_for_decision (the "await a resolution" path — a push via
Redis pub/sub, not a poll loop). Resolution typically arrives from a different
client (the human's rail), which is why pub/sub across connections matters.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from redis import asyncio as aioredis

from app.config import DATABASE_URL, MCP_ALLOWED_HOSTS, MCP_TRANSPORT, REDIS_URL
from app.exceptions import DecisionTimeout, NotFoundError
from app.models import Decision
from app.onboarding_config import DOCUMENTS
from app.services.conversation import spec_enrichment, summarize_conversation
from app.store import SpecStore


@dataclass
class Lifespan:
    store: SpecStore


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[Lifespan]:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis.ping()  # type: ignore  # redis.asyncio.ping is awaitable; stubs mistype it as sync
    try:
        yield Lifespan(store=SpecStore(pg, redis))
    finally:
        await pg.close()
        await redis.aclose()


# streamable_http_path="/" so that when mounted at /mcp on FastAPI the endpoint
# is reachable at http://host:8000/mcp (not /mcp/mcp).
#
# FastMCP defaults to host="127.0.0.1" which auto-enables DNS-rebinding protection
# (allowed_hosts=localhost only). In HTTP/Railway mode the Host header is the proxy
# hostname, so we configure protection explicitly: empty MCP_ALLOWED_HOSTS disables
# the check (safe for Railway/VPC where transport is already controlled).
if MCP_TRANSPORT == "http":
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(MCP_ALLOWED_HOSTS),
        allowed_hosts=MCP_ALLOWED_HOSTS.split(",") if MCP_ALLOWED_HOSTS else [],
    )
else:
    _transport_security = None

mcp = FastMCP("doen", lifespan=lifespan, streamable_http_path="/", transport_security=_transport_security)


def _store(ctx: Context) -> SpecStore:
    return ctx.request_context.lifespan_context.store


@mcp.tool()
async def get_spec(initiative_id: str, ctx: Context) -> dict:
    """Read the whole living spec for an initiative at its current version, plus the
    initiative's lifecycle context as `initiative: {id, title, state}`. Ground yourself in
    intent, constraints, discretion, acceptance — and state (0011: draft / building / complete;
    don't reshape a spec already `building`) — before acting.

    Enriched (0013 u5) with `advisor_summary` (the Advisor's latest guidance note for this
    initiative) and `unit_context` (per unit: the executor's submission summary, the human's
    verification feedback + verdict, and the Advisor's preliminary review notes) — so you see the
    reasoning around the work, not just the spec. Both are present only when that data exists."""
    store = _store(ctx)
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise ValueError(f"no spec for initiative {initiative_id}")
    out = spec.model_dump()
    init = await store.get_initiative(initiative_id)
    out["initiative"] = (
        {"id": init.id, "title": init.title, "state": init.state} if init else None
    )
    out.update(await spec_enrichment(store, initiative_id))
    return out


@mcp.tool()
async def get_conversation_summary(initiative_id: str, ctx: Context) -> dict:
    """Read WHY this spec is the way it is (0013 u5). Returns a compact, structured summary of the
    shaping conversation: `key_decisions` (each with the question, the option chosen, and the
    rationale), `rejected_alternatives` (the options that were considered and dropped), and
    `stated_priorities` (the human's own turns — what they said mattered). Use it to understand
    the intent behind the constraints before you build, so you don't re-decide what's settled."""
    return await summarize_conversation(_store(ctx), initiative_id)


@mcp.tool()
async def raise_decision(
    initiative_id: str,
    question: str,
    options: list[str],
    ctx: Context,
    recommendation: str | None = None,
) -> dict:
    """Surface a product/intent call that is outside the spec's constraints + discretion.
    Do not guess in code. Returns the open Decision; await it with wait_for_decision."""
    d = Decision(question=question, options=options, recommendation=recommendation)
    saved = await _store(ctx).raise_decision(d, initiative_id)
    return saved.model_dump()


@mcp.tool()
async def resolve_decision(
    decision_id: str,
    chosen: str,
    rationale: str,
    decided_by: str,
    ctx: Context,
) -> dict:
    """Record the human's verdict on an open decision and wake anyone awaiting it."""
    d = await _store(ctx).resolve_decision(decision_id, chosen, rationale, decided_by)
    return d.model_dump()


@mcp.tool()
async def wait_for_decision(decision_id: str, ctx: Context, timeout: float = 600) -> dict:
    """Block until a decision is resolved, then return it. Push via Redis pub/sub, not a
    poll loop. Raises if it is not resolved within `timeout` seconds."""
    try:
        d = await _store(ctx).wait_for_decision(decision_id, timeout=timeout)
    except DecisionTimeout:
        raise ValueError(f"decision {decision_id} not resolved within {timeout}s")
    return d.model_dump()


# --- BD-5 u2: criteria-as-tracking MCP tools ----------------------------------------
@mcp.tool()
async def submit_evidence(
    initiative_id: str,
    criteria_results: list[dict],
    ctx: Context,
) -> dict:
    """Submit evidence against acceptance criteria (BD-5). Each entry must include
    `criterion_id`, `result` ('pass' | 'fail' | 'needs_judgment'), and `evidence` (string).
    Sets `verification_status` to `evidence_submitted` on each criterion and bumps the spec
    version. All-or-nothing: if any `criterion_id` does not exist the whole call is rejected
    with no state change. Uses the same optimistic-lock guard as all spec edits."""
    try:
        spec = await _store(ctx).submit_evidence(initiative_id, criteria_results)
    except NotFoundError as e:
        raise ValueError(str(e))
    return {"version": spec.version, "updated_criteria": [r["criterion_id"] for r in criteria_results]}


@mcp.tool()
async def get_criteria_status(initiative_id: str, ctx: Context) -> dict:
    """Return all acceptance criteria for an initiative with their current
    `verification_status`, `evidence`, `verdict`, and `feedback` fields."""
    try:
        criteria = await _store(ctx).get_criteria_status(initiative_id)
    except NotFoundError as e:
        raise ValueError(str(e))
    return {"initiative_id": initiative_id, "criteria": criteria}


# --- organizational memory (spec 0005): retrieve relevant prior patterns -------------
@mcp.tool()
async def get_context(initiative_id: str, query: str, ctx: Context, limit: int = 8) -> dict:
    """Retrieve relevant prior patterns to ground the current work. Searches the memory
    corpus — resolved decisions and completed-initiative memory — ranked by similarity to
    `query`. Call it while shaping or building so you reuse what was decided and learned
    before instead of re-deciding it. Each hit is source-attributed (which initiative,
    decision vs. memory, a relevance score) so you can judge whether to trust it.

    `initiative_id` is your grounding context. If it belongs to a PROJECT (spec 0010), the
    search is project-scoped: sibling initiatives within the same project are searched first,
    falling back to the rest of the corpus only when project hits are insufficient. Each hit is
    tagged `scope` (project / global) so you can see what came from this body of work vs.
    elsewhere. A standalone initiative searches globally, as before."""
    store = _store(ctx)
    init = await store.get_initiative(initiative_id)
    project_id = init.project_id if init else None
    hits = await store.get_context(query, limit=limit, project_id=project_id)
    return {
        "initiative_id": initiative_id,
        "project_id": project_id,
        "query": query,
        "hits": [h.model_dump() for h in hits],
    }


# --- BD-9: project onboarding — write setup documents into the user's working directory ----
@mcp.tool()
async def setup_project(project_path: str, ctx: Context) -> dict:
    """Install the Doen onboarding documents into the given project directory (BD-9).

    Writes CLAUDE.md, agents.md, and docs/doen-setup.md from the server-side document
    manifest (app.onboarding_config.DOCUMENTS). Safe to re-run at any time — existing
    files are overwritten with the latest version (constraint item_97b5c68fb7bd: the flow
    must be re-triggerable without resetting project state).

    `project_path` is the absolute or relative path to the project root directory where
    files should be written. Pass "." to use the current working directory.

    Validates that the target directory exists before writing anything. If it does not
    exist, returns a descriptive error and writes no files (constraint item_06a45f4ca0ac).
    """
    root = Path(project_path).expanduser().resolve()
    if not root.exists():
        raise ValueError(
            f"project_path {str(root)!r} does not exist — "
            "pass an absolute path to an existing directory"
        )
    if not root.is_dir():
        raise ValueError(
            f"project_path {str(root)!r} is not a directory — "
            "pass the path to the project root folder, not a file"
        )

    written: list[str] = []
    for doc in DOCUMENTS:
        dest = root / doc.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(doc.content, encoding="utf-8")
        written.append(str(dest.relative_to(root)))

    return {
        "status": "ok",
        "project_path": str(root),
        "files_written": written,
        "message": (
            f"Installed {len(written)} file(s) into {str(root)!r}. "
            "You can re-run setup_project at any time to install updated docs."
        ),
    }


if __name__ == "__main__":
    mcp.run()
