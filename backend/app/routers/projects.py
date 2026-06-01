"""Projects: group initiatives under a strategic intent (spec 0010, u1).

Thin router — create/list/read projects, list a project's initiatives, and assign an
initiative to a project (or detach it). Domain errors map to HTTP centrally (exceptions).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.exceptions import NotFoundError, ValidationError
from app.models import Initiative, Message, Project
from app.schemas import (
    AdvisorTurn,
    AssignProject,
    CreateProject,
    PostMessage,
    ProjectDashboard,
    ShapeWithAI,
)
from app.services import advisor as advisor_service
from app.services import shaping as shaping_service
from app.store import SpecStore

router = APIRouter(tags=["projects"])

_Store = Annotated[SpecStore, Depends(get_store)]


@router.get("/projects")
async def list_projects(store: _Store) -> list[Project]:
    """Every project — the level above the dashboard (0010 a2)."""
    return await store.list_projects()


@router.post("/projects", status_code=201)
async def create_project(body: CreateProject, store: _Store) -> Project:
    """Create a project with a name + strategic intent (0010 a1)."""
    if not body.name.strip():
        raise ValidationError("project name must not be empty")
    return await store.create_project(body.name.strip(), body.intent.strip())


@router.get("/projects/{project_id}")
async def get_project(project_id: str, store: _Store) -> Project:
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    return project


@router.get("/projects/{project_id}/initiatives")
async def list_project_initiatives(project_id: str, store: _Store) -> list[Initiative]:
    """The initiatives grouped under a project (0010 a2/a7)."""
    if await store.get_project(project_id) is None:
        raise NotFoundError(f"no project {project_id}")
    return await store.list_project_initiatives(project_id)


@router.get("/projects/{project_id}/dashboard")
async def project_dashboard(project_id: str, store: _Store) -> ProjectDashboard:
    """The project dashboard (0010 a2): the project + its grouped initiatives + the count of
    open decisions across all of them, in one read."""
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    return ProjectDashboard(
        project=project,
        initiatives=await store.list_project_initiatives(project_id),
        open_decisions=await store.count_open_decisions(project_id),
        attention=await store.get_project_attention(project_id),
    )


@router.post("/projects/{project_id}/initiatives/shape", status_code=201)
async def create_initiative_from_description(
    project_id: str, body: ShapeWithAI, store: _Store
) -> Initiative:
    """Description-first creation (0011 C2/a3): the human describes what they want; the Advisor
    drafts the whole spec (title, intent, constraints, discretion, acceptance, units) — all
    proposed — and the initiative is scaffolded under it, ready to confirm item by item. A failed
    LLM call -> 502 leaves nothing created; an unknown project -> 404."""
    if not body.description.strip():
        raise ValidationError("a description is required to start an initiative")
    return await shaping_service.create_from_description(store, project_id, body.description)


@router.post("/initiatives/{initiative_id}/project")
async def assign_to_project(
    initiative_id: str, body: AssignProject, store: _Store
) -> Initiative:
    """Move an initiative to a (different) project — there is no detach (no orphan specs).
    A missing initiative or project -> 404."""
    return await store.assign_initiative_to_project(initiative_id, body.project_id)


# --- the project-level conversation rail (0010 u5): the Advisor scoped to the project ---
@router.get("/projects/{project_id}/messages")
async def project_messages(project_id: str, store: _Store) -> list[Message]:
    """The project rail's full history, oldest-first (a9)."""
    if await store.get_project(project_id) is None:
        raise NotFoundError(f"no project {project_id}")
    return await store.list_project_messages(project_id)


@router.post("/projects/{project_id}/advisor")
async def project_advisor(project_id: str, body: PostMessage, store: _Store) -> AdvisorTurn:
    """One turn on the project rail (a9/a10): the same Advisor, scoped to the whole project,
    reasoning across its initiatives. An LLMError -> 502; a missing project -> 404."""
    return await advisor_service.advise_project(store, project_id, body.content)
