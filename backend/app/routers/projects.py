"""Projects: group initiatives under a strategic intent (spec 0010, u1).

Thin router — create/list/read projects, list a project's initiatives, and assign an
initiative to a project (or detach it). Domain errors map to HTTP centrally (exceptions).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import get_store
from app.exceptions import NotFoundError, ValidationError
from app.models import Initiative, Message, Project, short_id, short_slug
from app.onboarding_config import SETUP_PROMPT
from app.schemas import (
    AdvisorReply,
    AdvisorRequest,
    AssignProject,
    CreateProject,
    OnboardingStatus,
    ProjectDashboard,
    ShapeWithAI,
    UpdateProject,
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
    """Create a project with a name + strategic intent (0010 a1), with an optional short prefix
    that's auto-derived from the name when omitted (0013 u2)."""
    if not body.name.strip():
        raise ValidationError("project name must not be empty")
    return await store.create_project(
        body.name.strip(), body.intent.strip(), prefix=body.prefix
    )


@router.get("/projects/{project_id}")
async def get_project(project_id: str, store: _Store) -> Project:
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    return project


@router.post("/projects/{project_id}/archive", status_code=200)
async def archive_project(project_id: str, store: _Store) -> Project:
    """Archive a project (BD-11, item_cef8f182b12e). Idempotent. The project stays accessible
    at its canonical URL; the archived flag signals the UI to show the archived indicator."""
    return await store.archive_project(project_id)


@router.post("/projects/{project_id}/unarchive", status_code=200)
async def unarchive_project(project_id: str, store: _Store) -> Project:
    """Restore an archived project to active state (BD-11, item_2e81fe09d18d). No data loss —
    all initiatives, specs, and decisions are untouched."""
    return await store.unarchive_project(project_id)


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: UpdateProject, store: _Store) -> Project:
    """Edit a project's intent inline from its dashboard (0013 u2). A no-op PATCH just re-reads."""
    if body.intent is None:
        project = await store.get_project(project_id)
        if project is None:
            raise NotFoundError(f"no project {project_id}")
        return project
    return await store.update_project(project_id, intent=body.intent.strip())


@router.get("/projects/{project_id}/initiatives")
async def list_project_initiatives(project_id: str, store: _Store) -> list[Initiative]:
    """The initiatives grouped under a project (0010 a2/a7)."""
    if await store.get_project(project_id) is None:
        raise NotFoundError(f"no project {project_id}")
    return await store.list_project_initiatives(project_id)


@router.get("/projects/{project_id}/dashboard")
async def project_dashboard(project_id: str, store: _Store) -> ProjectDashboard:
    """The project dashboard (0010 a2): the project + its grouped initiatives + the count of
    open decisions across all of them, in one read. Includes the onboarding prompt (BD-9) so
    the hint has everything it needs without a second round-trip."""
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    initiatives, open_decisions, pending_drift_reports, attention = await asyncio.gather(
        store.list_project_initiatives(project_id),
        store.count_open_decisions(project_id),
        store.count_pending_drift_reports(project_id),
        store.get_project_attention(project_id),
    )
    return ProjectDashboard(
        project=project,
        initiatives=initiatives,
        open_decisions=open_decisions,
        pending_drift_reports=pending_drift_reports,
        attention=attention,
        onboarding_prompt=SETUP_PROMPT,
    )


@router.get("/projects/{project_id}/specs/{ref}")
async def resolve_spec(project_id: str, ref: str, store: _Store) -> dict:
    """Resolve a short ref (`bd-7-slug`, or just `bd-7`) — or a legacy long initiative id — to
    its spec within the project, plus the canonical short id and slug (0012 u5, a10/a11). The
    URL key is the short, per-project id; the stable initiative id still drives every write
    underneath. The web redirects to the canonical slug when the ref isn't already it."""
    proj = await store.get_project(project_id)
    if proj is None:
        raise NotFoundError(f"no project {project_id}")
    init = await store.resolve_initiative(project_id, ref)
    if init is None:
        raise NotFoundError(f"no initiative {ref} in project {project_id}")
    spec = await store.get_spec(init.id)
    if spec is None:
        raise NotFoundError(f"no spec for initiative {init.id}")
    return {
        **spec.model_dump(),
        "short_id": short_id(proj.prefix, init.seq),
        "short_slug": short_slug(proj.prefix, init.seq, spec.title),
        # initiative_type is already in spec.model_dump() (mirrored at creation);
        # re-assert from the initiative row as the authoritative source.
        "initiative_type": init.initiative_type,
    }


@router.post("/projects/{project_id}/initiatives/shape", status_code=201)
async def create_initiative_from_description(
    project_id: str, body: ShapeWithAI, store: _Store
) -> Initiative:
    """Description-first creation (0011 C2/a3): the human describes what they want; the Advisor
    drafts the whole spec (title, intent, constraints, discretion, acceptance, units) — all
    proposed — and the initiative is scaffolded under it, ready to confirm item by item. A failed
    LLM call -> 502 leaves nothing created; an unknown project -> 404.
    BD-15: `initiative_type` in the body sets engineering vs. research framing."""
    if not body.description.strip():
        raise ValidationError("a description is required to start an initiative")
    return await shaping_service.create_from_description(
        store, project_id, body.description, initiative_type=body.initiative_type
    )


@router.post("/initiatives/{initiative_id}/project")
async def assign_to_project(
    initiative_id: str, body: AssignProject, store: _Store
) -> Initiative:
    """Move an initiative to a (different) project — there is no detach (no orphan specs).
    A missing initiative or project -> 404."""
    return await store.assign_initiative_to_project(initiative_id, body.project_id)


# --- onboarding (BD-9): hint state + dismissal, re-triggerable at any time ---------------
@router.get("/projects/{project_id}/onboarding")
async def get_onboarding_status(project_id: str, store: _Store) -> OnboardingStatus:
    """Return whether the onboarding hint has been dismissed and the copyable setup prompt."""
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"no project {project_id}")
    return OnboardingStatus(dismissed=project.onboarding_dismissed, prompt=SETUP_PROMPT)


@router.post("/projects/{project_id}/onboarding/dismiss", status_code=200)
async def dismiss_onboarding(project_id: str, store: _Store) -> OnboardingStatus:
    """Persist the hint dismissal server-side (constraint item_b8b031fbfe0f). Safe to call
    repeatedly — idempotent. The hint will not reappear on reload or a different session."""
    project = await store.dismiss_project_onboarding(project_id)
    return OnboardingStatus(dismissed=project.onboarding_dismissed, prompt=SETUP_PROMPT)


@router.post("/projects/{project_id}/onboarding/reset", status_code=200)
async def reset_onboarding(project_id: str, store: _Store) -> OnboardingStatus:
    """Re-enable the onboarding hint (constraint item_97b5c68fb7bd — flow must be re-triggerable
    at any time without resetting project state)."""
    project = await store.reset_project_onboarding(project_id)
    return OnboardingStatus(dismissed=project.onboarding_dismissed, prompt=SETUP_PROMPT)


# --- the project-level conversation rail (0010 u5; spec uvama): Advisor scoped to the project ---
@router.post("/projects/{project_id}/advisor", status_code=201)
async def project_advisor(project_id: str, body: AdvisorRequest, store: _Store) -> AdvisorReply:
    """One turn on the project rail (a9/a10): the same Advisor, scoped to the whole project,
    reasoning across its initiatives. The browser sends the windowed history; nothing is
    persisted (spec uvama). An LLMError -> 502; a missing project -> 404."""
    history = [
        Message(project_id=project_id, role=m.role, content=m.content) for m in body.history
    ]
    reply, proposed_initiative = await advisor_service.advise_project(
        store, project_id, body.content, history
    )
    return AdvisorReply(message=reply, proposed_initiative=proposed_initiative)
