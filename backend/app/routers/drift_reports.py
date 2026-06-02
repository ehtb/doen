"""Drift reports: human-gated resolution of agent-filed memory discrepancies (BD-12)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.database import get_store
from app.models import DriftReport
from app.store import SpecStore

router = APIRouter(tags=["drift_reports"])

_Store = Annotated[SpecStore, Depends(get_store)]


class ResolveDriftReport(BaseModel):
    action: str  # "approved" | "dismissed" | "initiative_created"
    resolution_note: str | None = None
    memory_update: dict | None = None  # optional {summary?, learnings?} for action="approved"


@router.get("/projects/{project_id}/drift-reports")
async def list_drift_reports(
    project_id: str, store: _Store, status: str | None = None
) -> list[DriftReport]:
    """All drift reports for a project's memory, optionally filtered by status."""
    return await store.list_drift_reports_by_project(project_id, status=status)


@router.post("/drift-reports/{report_id}/resolve")
async def resolve_drift_report(
    report_id: str, body: ResolveDriftReport, store: _Store
) -> DriftReport:
    """Human resolves a drift report: approve (and optionally update memory), dismiss, or
    mark as initiative_created. Memory is only mutated on action='approved'."""
    return await store.resolve_drift_report(
        report_id,
        action=body.action,
        memory_update=body.memory_update,
        resolution_note=body.resolution_note,
    )
