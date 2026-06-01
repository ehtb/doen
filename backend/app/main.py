"""Doen backend entrypoint — the FastAPI app factory.

This module just assembles the app: the lifespan (shared pool + Redis), the domain
exception handlers (error mapping lives in app.exceptions), and the per-domain routers.
Models, schemas, services, repository, and providers each live in their own module.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from app.database import lifespan
from app.exceptions import register_exception_handlers
from app.routers import decisions, initiatives, learn, shaping, specs, units


def create_app() -> FastAPI:
    app = FastAPI(title="Doen", lifespan=lifespan)
    register_exception_handlers(app)
    for module in (initiatives, specs, decisions, units, learn, shaping):
        app.include_router(module.router)

    @app.get("/health")
    async def health(request: Request) -> dict:
        pg_ok = await request.app.state.pg.fetchval("SELECT 1") == 1
        redis_ok = bool(await request.app.state.redis.ping())
        return {
            "status": "ok" if pg_ok and redis_ok else "degraded",
            "postgres": pg_ok,
            "redis": redis_ok,
        }

    return app


app = create_app()
