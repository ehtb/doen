"""Seed spec 0010 — Projects & cross-initiative intelligence — INTO Doen.

Follows the `build-doen-000N-name` convention. Items seed as proposed; the human confirms
in the UI.

Two shaping decisions were resolved by the author in-session, folded into the items per the
0006 precedent (no open decision row is seeded):
  D1 (one project per initiative vs many-to-many) -> (a) one project per initiative — a simple
     nullable FK. Global memory search already surfaces cross-project relevance by embedding
     similarity, so the org link stays flat. Folded into constraint 1.
  D2 (project rail: separate Advisor vs same Advisor, scoped) -> (a) one Advisor, scoped. The
     system prompt already adapts by stage (0009); it gains a project-level mode alongside the
     stage modes — strategic on the project dashboard, tactical inside an initiative. Folded
     into constraint 2 + a9/a10.

Planned decomposition (proposed later via MCP propose_unit during decompose, NOT seeded):
  u1 projects table + model + migration (project_id FK, build-doen migration)      -> a1, a7, a8
  u2 project dashboard (grouped initiatives, intent, aggregate status)             -> a2
  u3 Advisor project-aware context assembly (compact sibling summaries)            -> a3, a5
  u4 project-scoped get_context + get_guidance (project-first, global fallback)    -> a4, a6
  u5 project-level conversation rail (same Advisor, project scope)                 -> a9, a10

    cd backend && .venv/bin/python -m app.seed_0010
"""

from __future__ import annotations

import asyncio

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, DEV_ORG_ID, DEV_USER_ID, REDIS_URL
from app.models import AcceptanceCriterion, Reference, Spec, SpecItem, Verify
from app.store import SpecStore

INITIATIVE_ID = "build-doen-0010-projects"
TITLE = "Projects & cross-initiative intelligence"

_DRAFT = dict(provenance="ai_proposed", status="proposed")

_INTENT = """Nine initiatives have built Doen and each one is a standalone story. Memory \
connects them by similarity — get_context finds relevant decisions by embedding distance — but \
there's no structure that says "these belong together" and no way for the Advisor to reason \
about them as a coherent body of work. A contradiction between initiative 0003's constraints \
and initiative 0007's can only be caught if a human remembers both. A pattern that spans three \
initiatives is invisible unless someone asks exactly the right get_context query. Projects fix \
this by turning a bag of initiatives into an intelligible whole. A project groups related \
initiatives under a shared strategic intent and becomes a context boundary for the Advisor: \
when operating inside a project, the Advisor sees the entire project's history — sibling \
initiatives' specs, decisions, and outcomes — and can reason across them. "This new constraint \
contradicts a decision from 0004." "Three of your last five initiatives hit migration issues in \
the first unit." "Initiative 0007 depends on a constraint from 0003 that was retired." This is \
cross-initiative intelligence, and it makes the Advisor fundamentally smarter without the human \
having to hold the whole picture in their head. For dogfooding this is immediate: "Build Doen" \
becomes a project. All completed initiatives are grouped under it. The Advisor can reason about \
the full build history when shaping what comes next."""

_CONSTRAINTS = [
    "Projects table: id (slug), name, intent (the strategic goal, prose), created_at, "
    "updated_at. Every initiative belongs to a project — project_id is a required (NOT NULL) FK, "
    "with ON DELETE RESTRICT so a project can't be deleted while it still owns initiatives. There "
    "are no orphan specs. (D1 resolved -> a: one project per initiative — a flat FK, NOT a "
    "many-to-many junction. Global memory search already surfaces cross-project relevance by "
    "embedding similarity, so the organisational link stays flat; revisit only if real users hit "
    "the wall.)",
    "The Advisor's context expands inside a project. When the initiative belongs to a project, "
    "the system prompt includes: the project's strategic intent, compact summaries of sibling "
    "initiatives (title, stage, confirmed constraint count, key decisions), and project-scoped "
    "memory. The Advisor is explicitly prompted to check for cross-initiative coherence: "
    "contradictions, dependency gaps, repeated patterns. (D2 resolved -> a: one Advisor, scoped "
    "— NOT a separate \"Project Advisor\" persona. The prompt already adapts by stage (0009); it "
    "gains a project-level mode alongside the stage modes — strategic on the project dashboard, "
    "tactical inside an initiative.)",
    "Compact summaries, not full specs. Including every sibling initiative's full spec in every "
    "Advisor call is not acceptable — token cost scales with project size. Use compact summaries "
    "for awareness and project-scoped get_context for relevant specifics on demand. The Advisor "
    "knows what exists; it retrieves details only when reasoning requires them.",
    "get_context gains a project scope. When called from a project initiative, it searches "
    "decisions and memory within the project first, then falls back to global. Results are tagged "
    "with their source initiative for transparency.",
    "get_guidance draws on project context. Briefings for a unit in a project initiative include "
    "sibling awareness — relevant cross-initiative decisions, constraints that may bear on this "
    "unit's scope, known patterns from the project's history.",
    "Migration creates a \"build-doen\" project and assigns all existing initiatives to it. No "
    "initiative is orphaned.",
    "No auth this slice — single dev user.",
]

_DISCRETION = [
    "Compact summary format: what to include per sibling (title + stage + constraint headlines + "
    "key decisions is a reasonable starting point; tune for token cost vs. awareness).",
    "Project dashboard layout and what aggregate information to show (initiative count by stage, "
    "open decisions across the project, latest activity).",
    "Whether the project intent is authored through the Advisor (like spec shaping) or via direct "
    "editing only.",
    "How cross-initiative concerns are surfaced: in the initiative's rail, on the project "
    "dashboard, or both.",
    "How get_context blends project and global results (project first then global; interleaved by "
    "relevance; or project-only with a manual global fallback).",
    "Whether to show cross-initiative dependency links visually (e.g. \"depends on 0001\") on the "
    "project dashboard or leave it to the Advisor to surface them in conversation.",
    "Navigation structure: projects as a level above the current dashboard, or the dashboard "
    "shows both standalone initiatives and project groups.",
]

# (text, verify kind, verify detail)
_ACCEPTANCE = [
    ("A project can be created with a name and intent. An initiative can be assigned to a "
     "project. The project-initiative relationship persists.", "test",
     "Create a project with a name + intent; assign an initiative; reload — the initiative's "
     "project_id persists and the project lists it."),
    ("A project dashboard shows all grouped initiatives with their title, stage, and navigation "
     "to each initiative's spec. The project's intent is visible.", "behavior",
     "Open the project dashboard; every grouped initiative shows title + stage and links to its "
     "spec; the project's strategic intent is shown."),
    ("The Advisor operating within a project initiative demonstrates cross-initiative awareness — "
     "it references sibling initiatives' constraints, decisions, or patterns without being "
     "explicitly prompted to look at them.", "behavior",
     "Talk to the Advisor inside a project initiative; unprompted, it cites a sibling "
     "initiative's constraint / decision / pattern."),
    ("get_context called from a project initiative returns results from sibling initiatives "
     "within the same project, tagged with their source initiative. Global fallback returns "
     "results from outside the project when project results are insufficient.", "test",
     "Call get_context from a project initiative; hits are project-first and source-tagged; a "
     "thin project falls back to global hits."),
    ("The Advisor flags a cross-initiative concern unprompted during a conversation: a "
     "contradiction between constraints in different initiatives, a dependency on a retired item, "
     "or a pattern repeated across multiple initiatives.", "behavior",
     "Seed a contradiction across two sibling specs; in conversation the Advisor surfaces it "
     "without being asked to compare."),
    ("get_guidance for a unit in a project initiative includes project-level context: relevant "
     "decisions or constraints from sibling initiatives that bear on this unit.", "behavior",
     "Call get_guidance for a unit in a project initiative; the briefing references a sibling "
     "initiative's decision or constraint relevant to the unit's scope."),
    ("Migration creates a \"build-doen\" project and assigns all existing initiatives. No "
     "initiative is left unassigned; the project dashboard shows the full history.", "test",
     "Run the migration; a build-doen project exists, every existing initiative has its "
     "project_id, and the project lists them all."),
    ("Every initiative belongs to a project (project_id NOT NULL); creating or moving an "
     "initiative without a valid project is rejected — there are no orphan specs. The existing "
     "per-initiative flows — the Advisor, spec editing, memory, and the rail — are unaffected for "
     "a project initiative.", "test",
     "Create an initiative with no project -> rejected; with a project -> it persists under it; "
     "shaping, editing, memory, and the rail behave as before."),
    ("A project-level conversation rail on the project dashboard allows the human to discuss the "
     "project as a whole with the Advisor: \"how is this project going?\", \"what should I build "
     "next?\", \"are there contradictions across initiatives?\"", "behavior",
     "On the project dashboard, ask the Advisor a whole-project question; it answers across the "
     "grouped initiatives, not one in focus."),
    ("Within the \"Build Doen\" project, the Advisor reasons across the full history of completed "
     "initiatives as one coherent body of work — surfacing cross-cutting patterns, flagging "
     "contradictions, and drawing on the entire project's experience when shaping or guiding new "
     "initiatives. The project feels like a whole, not a list. [HEADLINE]", "human_judgment",
     "Inside Build Doen, the Advisor reasons across the whole build history — patterns, "
     "contradictions, prior experience — when shaping or guiding; the project feels whole."),
]

_REFERENCES = [
    ("code", "backend/app/store.py",
     "get_context (memory retrieval) gains a project scope, and where project CRUD + the "
     "project_id FK + sibling-summary assembly live — u1 / u3 / u4 / constraints 1, 3, 4."),
    ("code", "backend/app/services/advisor.py",
     "the stage-aware Advisor whose system prompt gains a project-level mode + compact sibling "
     "summaries (one Advisor, scoped) — D2 / u3 / a3 / a5."),
    ("code", "backend/app/services/guidance.py",
     "the unit briefing that gains project-level context — relevant sibling decisions/constraints "
     "— u4 / a6 / constraint 5."),
    ("code", "backend/app/mcp_server.py",
     "get_context + get_guidance, the executor-facing tools that gain project scope — u4 / a4 / "
     "a6."),
    ("code", "web/app/specs/[id]/ConversationRail.tsx",
     "the rail component reused for the project-level rail on the project dashboard (same "
     "component, project-scoped context) — u5 / a9 / a10."),
    ("prior_initiative", "build-doen-0004-initiative-lifecycle",
     "the initiatives table + dashboard this slice groups into projects, and the parent-entity "
     "model project_id extends — u1 / u2."),
    ("prior_initiative", "build-doen-0005-memory-learn-stage",
     "get_context + the memory corpus the project scope partitions and the Advisor reasons over — "
     "u4 / a4."),
    ("prior_initiative", "build-doen-0009-conversation-rail",
     "the Advisor, the conversation rail, and get_guidance this slice widens to project scope — "
     "constraint 2 / u3 / u4 / u5."),
    ("doc", "docs/spec-contract.md",
     "the spec-contract discipline the Advisor checks across sibling initiatives for coherence — "
     "constraint 2 / u3."),
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
