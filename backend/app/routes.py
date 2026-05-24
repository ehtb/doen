"""HTTP surface for the spec slice (u2).

Endpoints:
  POST /initiatives        — create the parent row a spec hangs off of (dev-owned).
  PUT  /specs/{id}         — create-or-update the living spec; 409 on a stale version.
  GET  /specs/{id}         — the whole spec in one call (warm reads come from Redis).
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

import asyncpg
from asyncpg.exceptions import ForeignKeyViolationError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import DEV_ORG_ID, DEV_USER_ID
from app.deps import get_pool, get_store
from app.store import Spec, SpecStore, Stage, StaleSpecError

router = APIRouter()


class CreateInitiative(BaseModel):
    appetite: str | None = None
    stage: Stage = "shape"


@router.post("/initiatives", status_code=201)
async def create_initiative(
    body: CreateInitiative,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> dict:
    initiative_id = f"init_{uuid4().hex[:12]}"
    row = await pool.fetchrow(
        """INSERT INTO initiatives (id, org_id, owner_id, appetite, stage)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING id, org_id, owner_id, appetite, stage, created_at""",
        initiative_id, DEV_ORG_ID, DEV_USER_ID, body.appetite, body.stage,
    )
    return dict(row)


@router.put("/specs/{initiative_id}")
async def save_spec(
    initiative_id: str,
    spec: Spec,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    if spec.initiative_id != initiative_id:
        raise HTTPException(400, "initiative_id in path and body must match")
    try:
        return await store.save_spec(spec)
    except StaleSpecError as e:
        raise HTTPException(409, str(e))
    except ForeignKeyViolationError:
        raise HTTPException(404, f"initiative {initiative_id} does not exist")


@router.get("/specs/{initiative_id}")
async def read_spec(
    initiative_id: str,
    store: Annotated[SpecStore, Depends(get_store)],
) -> Spec:
    spec = await store.get_spec(initiative_id)
    if spec is None:
        raise HTTPException(404, f"no spec for initiative {initiative_id}")
    return spec
