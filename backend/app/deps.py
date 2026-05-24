"""FastAPI dependencies over the shared connections owned by the lifespan."""

from __future__ import annotations

import asyncpg
from fastapi import Request

from app.store import SpecStore


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pg


def get_store(request: Request) -> SpecStore:
    """Per-request SpecStore over the shared pool + redis client."""
    return SpecStore(request.app.state.pg, request.app.state.redis)
