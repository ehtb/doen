"""Doen backend entrypoint — the FastAPI app factory.

This module just assembles the app: the lifespan (shared pool + Redis), the domain
exception handlers (error mapping lives in app.exceptions), and the per-domain routers.
Models, schemas, services, repository, and providers each live in their own module.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.config import MCP_TRANSPORT
from app import database
from app.exceptions import register_exception_handlers
from app.routers import (
    conversation,
    decisions,
    initiatives,
    learn,
    projects,
    shaping,
    specs,
)


def create_app() -> FastAPI:
    if MCP_TRANSPORT == "http":
        # WARNING: HTTP MCP is intended for VPC/private network deployment only.
        # Do not expose to the public internet without authentication (see spec 0007).
        from app.mcp_server import mcp  # imported here to avoid loading it in stdio mode

        # Create once so the same instance is both mounted and lifecycle-managed.
        # Starlette does not propagate lifespan events to mounted sub-apps, so we
        # explicitly nest the MCP lifespan inside our own.
        mcp_http_app = mcp.streamable_http_app()

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with database.lifespan(app):
                async with mcp_http_app.router.lifespan_context(mcp_http_app):
                    yield
    else:
        lifespan = database.lifespan

    app = FastAPI(title="Doen", lifespan=lifespan)
    register_exception_handlers(app)
    for module in (initiatives, specs, decisions, learn, shaping, conversation, projects):
        app.include_router(module.router)

    @app.get("/health")
    async def health(request: Request, response: Response) -> dict:
        try:
            pg_ok = await request.app.state.pg.fetchval("SELECT 1") == 1
        except Exception:
            pg_ok = False
        try:
            redis_ok = bool(await request.app.state.redis.ping())
        except Exception:
            redis_ok = False
        ok = pg_ok and redis_ok
        if not ok:
            response.status_code = 503
        return {"status": "ok" if ok else "degraded", "postgres": pg_ok, "redis": redis_ok}

    if MCP_TRANSPORT == "http":
        app.mount("/mcp", mcp_http_app)

    return app


app = create_app()
