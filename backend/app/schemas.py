"""API request/response models — the HTTP boundary's shapes.

Distinct from app.models (the durable domain) on purpose: these describe what a client
sends and gets back. They reference domain models where a response embeds one (e.g. the
Learn review), but the request bodies are their own thing — a router never takes a raw
domain model off the wire except where a full Spec round-trips (PUT /specs/{id}).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.config import DEV_USER_ID
from app.models import Decision, Initiative, Memory, Section, Stage, Verify, WorkUnit


# --- initiatives + lifecycle ---------------------------------------------------------
class CreateInitiative(BaseModel):
    title: str


class SetStage(BaseModel):
    stage: Stage  # the target stage — must be one lifecycle step from the current one


# --- steering rail -------------------------------------------------------------------
class ResolveDecision(BaseModel):
    chosen: str
    rationale: str
    decided_by: str = DEV_USER_ID  # single dev user this slice; auth replaces this


# --- spec authoring ------------------------------------------------------------------
# The `version` on each request is the optimistic lock surfaced to the editor: the version
# the human last saw. save_spec re-checks it under a row lock, so a stale edit is rejected
# (409) rather than clobbering a concurrent change.
class AddItem(BaseModel):
    section: Section
    text: str
    version: int
    verify: Verify | None = None  # required iff section == "acceptance"


class EditItem(BaseModel):
    text: str
    version: int


class ItemVersion(BaseModel):
    version: int


class ConfirmAll(BaseModel):
    version: int
    section: Section | None = None  # None = every section


# --- work units ----------------------------------------------------------------------
class UnitVerdict(BaseModel):
    verdict: Literal["approved", "changes_requested"]
    feedback: str = ""
    decided_by: str = DEV_USER_ID


# --- AI-assisted shaping -------------------------------------------------------------
class ShapeWithAI(BaseModel):
    description: str


# --- learn stage ---------------------------------------------------------------------
class LearnReview(BaseModel):
    initiative: Initiative
    intent: str
    decisions: list[Decision]  # resolved only — the reasoning behind what shipped
    units: list[WorkUnit]
    memory: list[Memory]


class SubmitLearn(BaseModel):
    summary: str
    learnings: str | None = None
    outcome: dict | None = None
