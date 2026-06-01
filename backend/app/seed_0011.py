"""Seed spec 0011 — Guiding the human — INTO Doen.

Follows the `build-doen-000N-name` convention. Items seed as proposed; the human confirms
in the UI.

Two shaping decisions were resolved by the author in-session, folded into the items per the
0006 precedent (no open decision row is seeded):
  D1 (rejecting an ai_proposed item: delete vs retire) -> (c) delete from the spec, log the
     rejection in the conversation rail. The spec is a contract, not an archive — retired bad
     proposals make it harder to trust and read. The rail already records what was proposed and
     rejected, so the context lives in the dialogue, not the document. Folded into constraint 5.
  D2 (auto-inferred state transitions: reversible?) -> (c) the state is PURELY inferred from the
     data. No unit active -> Draft; any unit active -> Building; all done + learn -> Complete. It
     can't drift because it IS reality — no manual override, no "forgot to advance". Folded into
     constraint 1.

Planned decomposition (proposed later via MCP propose_unit during shaping, NOT seeded):
  u1 lifecycle simplification (7-stage -> 3-state, inferred transitions, migration)   -> a1, a2
  u2 description-first creation (description -> Advisor shaping; scale-aware prompt)   -> a3, a7
  u3 mandatory project membership (no nullable project_id; migrate orphans)           -> a4
  u4 attention-driven spec page (attention surface + prominent per-item Accept/Reject) -> a5, a6
  u5 project screen as mission control (group by state, attention indicators)         -> a8, a9

    cd backend && .venv/bin/python -m app.seed_0011
"""

from __future__ import annotations

import asyncio

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, DEV_ORG_ID, DEV_USER_ID, REDIS_URL
from app.models import AcceptanceCriterion, Reference, Spec, SpecItem, Verify
from app.store import SpecStore

INITIATIVE_ID = "build-doen-0011-guiding-the-human"
TITLE = "Guiding the human"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """The capabilities are all there — shaping, editing, units, verification, memory, the \
Advisor, projects. But the human using them feels lost. The seven-stage lifecycle is ceremony \
nobody remembers to advance. Creation starts with a title instead of an intent. The spec page is \
a long document where actionable items are buried below the fold. Quick bug fixes go through the \
same heavyweight flow as multi-week features. The project screen is a flat list with no sense of \
priority. The product was designed around the spec contract — a clean conceptual model. This spec \
redesigns it around what the human actually does: describe what I want, confirm the parts that \
are right, know what needs my attention, see where everything stands. The capabilities don't \
change. The experience catches up."""

_CONSTRAINTS = [
    "Three lifecycle states, not seven: Draft -> Building -> Complete. Draft: the spec is being "
    "shaped, nothing is under construction. Building: at least one unit is in progress or in "
    "verification. Complete: all units are done, learnings captured. Transitions are INFERRED from "
    "the data, not manually advanced — the first unit moving to in_progress flips the initiative to "
    "Building; all units reaching done plus a confirmed learn entry flips to Complete. No manual "
    "stage buttons to forget. (D2 resolved -> c: the state is purely inferred and reversible by "
    "data — no unit active -> Draft, any unit active -> Building, all done + learn -> Complete. It "
    "can't drift because it is reality; no manual override.)",
    "Creation starts with a description, from the project screen. The user describes what they want "
    "(free text). The Advisor shapes it: generates a title, intent, constraints, discretion, "
    "acceptance criteria, and proposed units — all as ai_proposed. The human confirms item by item. "
    "There is no separate \"create initiative then shape it\" — creation IS shaping.",
    "All initiatives belong to a project. Remove nullable project_id. No orphan specs. If a quick "
    "fix doesn't fit an existing project, the user creates or uses a catch-all project (e.g. "
    "\"Maintenance\"). Existing standalone initiatives are migrated to a default project.",
    "The spec page leads with what needs your attention. An attention surface at the top shows: "
    "items awaiting confirmation (with inline Accept / Reject), open decisions, units in "
    "verification awaiting your verdict. The full spec (intent, constraints, discretion, criteria, "
    "units, learn) is the reference below — always accessible, not the landing state.",
    "Per-item Accept / Reject is prominent on every ai_proposed item. Not buried in an edit menu. "
    "Each proposed constraint, discretion item, and acceptance criterion shows clear action "
    "buttons. Confirming is the primary action; rejecting removes the item. Confirmed items show as "
    "solid/governed; proposed items show as pending review. (D1 resolved -> c: rejecting DELETES "
    "the item from the spec and logs the rejection in the conversation rail — the spec stays a "
    "clean contract; the history of what was proposed and rejected lives in the dialogue.)",
    "The Advisor sizes its proposal to the work. A bug-fix description produces a lightweight spec: "
    "one constraint, one acceptance criterion, one unit. A feature description produces the full "
    "structure. The Advisor infers scope from the description — no manual \"quick mode\" or size "
    "selector. The system prompt is updated to recognise initiative scale and propose "
    "proportionally.",
    "The project screen groups initiatives by state (Draft / Building / Complete) with attention "
    "indicators per initiative (items to confirm, decisions open, units to verify). It is the "
    "primary navigation surface — the first thing a user sees.",
]

_DISCRETION = [
    "How the attention surface is visually structured (cards, a sidebar, a pinned top section, a "
    "collapsible panel).",
    "Whether the attention surface aggregates across item types or groups them (all pending items "
    "in one list vs. separate sections for items / decisions / units).",
    "How the Advisor's scale inference works in the system prompt (heuristic from description "
    "length and keywords, or an explicit classification step before shaping).",
    "The project screen's grouping layout: columns (kanban-style by state), rows with headers, or a "
    "different pattern.",
    "What \"attention indicators\" look like on the project screen (badges, counts, icons, colour).",
    "Whether to show a progress indicator per initiative on the project screen (e.g. 3/5 units "
    "done) or just the state.",
    "How to handle the migration of existing 7-stage data to the 3-state model (map discover/shape/"
    "bet/decompose -> Draft; implement/verify -> Building; learn -> Complete).",
    "Animation or transition when an initiative auto-advances state (subtle indicator that the "
    "system noticed the change, not a silent flip).",
    "Whether the full spec is in a scrollable section, a collapsible accordion, or tabbed "
    "(constraints / criteria / units as tabs).",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("Initiatives have three states: Draft, Building, Complete. The 7-stage model is replaced. "
     "Migration maps existing stages correctly.", "test",
     "The lifecycle is draft/building/complete; the migration maps discover/shape/bet/decompose -> "
     "draft, implement/verify -> building, learn -> complete."),
    ("State transitions are automatic: first unit reaching in_progress -> Building; all units done "
     "+ learn captured -> Complete. No manual advance required.", "test",
     "Start a unit -> the initiative is Building; finish every unit and capture learn -> Complete; "
     "no manual stage call exists."),
    ("Creating an initiative from the project screen starts with a description input. The Advisor "
     "generates a full proposed spec (title, intent, constraints, discretion, criteria, units). The "
     "human reviews and confirms item by item.", "behavior",
     "From a project, describe a feature; the Advisor returns a proposed spec across all sections; "
     "the human confirms items one by one."),
    ("Every initiative belongs to a project. project_id is not nullable. Standalone initiatives are "
     "migrated to a default project.", "test",
     "project_id is NOT NULL; no orphan initiatives exist after migration; creation without a "
     "project is rejected."),
    ("The spec page shows an attention surface at the top: items awaiting confirmation, open "
     "decisions, units awaiting verdict. Each item has inline Accept / Reject. The count updates "
     "live as items are confirmed or rejected.", "behavior",
     "Open a spec with proposed items / open decisions / submitted units; the top surface lists "
     "them with inline actions; confirming/rejecting updates the count live."),
    ("Every ai_proposed item (constraint, discretion, acceptance criterion, work unit) shows "
     "prominent Accept / Reject actions. Confirming makes it governing; rejecting removes it. The "
     "visual distinction between proposed and confirmed is immediate and clear.", "behavior",
     "Each proposed item shows Accept / Reject up front; accept -> governing, reject -> removed; "
     "proposed vs confirmed are visually distinct at a glance."),
    ("A bug-fix-scale description (\"fix the misaligned login button\") produces a lightweight spec: "
     "~1 constraint, ~1 criterion, ~1 unit. A feature-scale description produces a full spec with "
     "multiple items and units. The Advisor adapts without being told the scale.", "behavior",
     "A bug-fix description yields a minimal spec; a feature description yields a full one — the "
     "Advisor infers scale from the description alone."),
    ("The project screen groups initiatives by state (Draft / Building / Complete) with attention "
     "indicators showing what needs action. Initiatives are navigable to their spec pages.",
     "behavior",
     "The project screen shows initiatives grouped by state with per-initiative attention "
     "indicators; each links to its spec page."),
    ("A user landing on Doen knows immediately: where things stand (project screen), what needs "
     "attention (attention indicators), and what to do next (accept/reject items, resolve "
     "decisions, verify units). The product guides rather than presents. Nobody feels lost. "
     "[HEADLINE]", "human_judgment",
     "A first-time user, unprompted, can say where things stand, what needs them, and what to do "
     "next — the product guides rather than presents."),
]

_REFERENCES = [
    ("code", "backend/app/models.py",
     "the lifecycle: State + derive_state replaces the 7-stage Stage; project_id required — u1 / "
     "u3 / constraints 1, 3."),
    ("code", "backend/app/store.py",
     "_recompute_state infers the lifecycle from work units + learn on every transition; creation "
     "enforces project membership — u1 / u3 / a2 / a4."),
    ("code", "backend/app/services/advisor.py",
     "the Advisor's state-aware modes + scale-aware shaping (lightweight vs full) and the rejection "
     "logged to the rail — u2 / u4 / a3 / a6 / a7."),
    ("code", "web/app/projects/[id]/page.tsx",
     "the project screen that becomes mission control — grouped by state with attention indicators "
     "— u5 / a8 / a9."),
    ("code", "web/app/projects/[id]/specs/[specId]/page.tsx",
     "the spec page that leads with the attention surface and prominent per-item Accept / Reject — "
     "u4 / a5 / a6."),
    ("prior_initiative", "build-doen-0004-initiative-lifecycle",
     "the 7-stage lifecycle this slice replaces with 3 inferred states — u1 / a1 / a2."),
    ("prior_initiative", "build-doen-0006-ai-assisted-spec-shaping",
     "the one-shot full-draft shaping that becomes the description-first creation flow — u2 / a3."),
    ("prior_initiative", "build-doen-0009-conversation-rail",
     "the Advisor + rail that drives creation-by-shaping and records rejected proposals — u2 / u4 / "
     "a3 / a6."),
    ("prior_initiative", "build-doen-0010-projects",
     "projects + the project dashboard this slice turns into the primary navigation surface — u3 / "
     "u5 / a4 / a8."),
]


def build_spec() -> Spec:
    return Spec(
        initiative_id=INITIATIVE_ID,
        state="draft",
        title=TITLE,
        intent=_INTENT,
        constraints=[SpecItem(text=t, **_DRAFT) for t in _CONSTRAINTS],
        discretion=[SpecItem(text=t, **_DRAFT) for t in _DISCRETION],
        acceptance=[
            AcceptanceCriterion(text=t, verify=Verify(kind=k, detail=d), **_DRAFT)
            for (t, k, d) in _ACCEPTANCE
        ],
        references=[Reference(kind=k, pointer=p, note=n) for (k, p, n) in _REFERENCES],
    )


async def seed() -> None:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pg, redis)
    try:
        await pg.execute(
            """INSERT INTO initiatives (id, org_id, owner_id, appetite, state, title, project_id)
               VALUES ($1, $2, $3, $4, 'draft', $5, 'build-doen')
               ON CONFLICT (id) DO NOTHING""",
            INITIATIVE_ID, DEV_ORG_ID, DEV_USER_ID, "small", TITLE,
        )
        existing = await store.get_spec(INITIATIVE_ID)
        if existing is not None:
            print(f"spec for '{INITIATIVE_ID}' already present (v{existing.version}); "
                  "leaving it untouched")
            return
        saved = await store.save_spec(build_spec())
        print(f"seeded '{INITIATIVE_ID}' spec v{saved.version}: {saved.title}")
    finally:
        await pg.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(seed())
