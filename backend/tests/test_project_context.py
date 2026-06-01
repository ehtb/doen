"""u3 — the Advisor's project-aware context assembly (spec 0010).

The compact sibling summaries are where this slice lives or dies (constraint 3): enough for
the Advisor to spot contradictions and patterns across initiatives, without serialising every
sibling spec into the prompt. These tests cover the assembly + rendering (LLM-free): the
sibling summary shape, that an initiative's context carries its project siblings, the
project-scoped get_context + get_guidance, and the project-level rail. The unprompted
cross-initiative reasoning itself (a3, a5) is a behavior AC, verified live against the real
Build Doen history.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.models import Decision, Message, ProjectContext, SpecItem, WorkUnit
from app.providers.embeddings import EmbeddingProvider
from app.services.advisor import (
    PROJECT_COHERENCE_PROMPT,
    _converse_project,
    advise_project,
    build_system_prompt,
    build_user_message,
)
from app.services.conversation import assemble_context
from app.services.guidance import generate_guidance
from app.store import SpecStore

DIM = 1536


def _store_run(
    fn: Callable[[SpecStore], Awaitable[object]],
    embedder: EmbeddingProvider | None = None,
) -> object:
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis, embedder=embedder))
        finally:
            await pg.close()
            await redis.aclose()

    return asyncio.run(go())


class FakeEmbedder:
    """Deterministic, key-free embeddings: identical text -> identical vector (distance 0),
    different text -> uncorrelated vector. Enough to assert scope/tagging without a real model."""

    dimension = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


class FakeLLM:
    def __init__(self, proposed_initiative: str | None = None) -> None:
        self.calls: list[dict] = []
        # BD-1 u3: when set, the project rail's structured reply carries a synthesised
        # proposed-initiative description (the crystallised-into-an-initiative case).
        self._proposed_initiative = proposed_initiative

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if schema_name == "advisor_reply":
            out = {"reply": "Three initiatives are in shape; 0009 is the one to close out next."}
            if self._proposed_initiative is not None:
                out["proposed_initiative"] = self._proposed_initiative
            return out
        return {"briefing": "Reuse the project's Postgres+Redis pattern.", "pitfalls": ["don't add a queue"]}


@pytest.fixture
def track_initiatives():
    ids: list[str] = []
    yield ids

    async def drop() -> None:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            for i in ids:
                await c.execute("DELETE FROM initiatives WHERE id = $1", i)
        finally:
            await c.close()

    asyncio.run(drop())


@pytest.fixture
def track_projects():
    ids: list[str] = []
    yield ids

    async def drop() -> None:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            for i in ids:
                # FK is ON DELETE RESTRICT — clear the project's initiatives first.
                await c.execute("DELETE FROM initiatives WHERE project_id = $1", i)
                await c.execute("DELETE FROM projects WHERE id = $1", i)
        finally:
            await c.close()

    asyncio.run(drop())


async def _add_confirmed_constraints(store: SpecStore, iid: str, texts: list[str]) -> None:
    spec = await store.get_spec(iid)
    assert spec is not None
    for t in texts:
        spec.constraints.append(SpecItem(text=t, provenance="human", status="confirmed"))
    await store.save_spec(spec)


async def _build_project_with_two_siblings(
    store: SpecStore, projects: list[str], inits: list[str]
) -> tuple[str, str, str]:
    """A project with sibling A (constraints + a resolved decision) and sibling B (the one in
    focus). Returns (project_id, sibling_a_id, sibling_b_id)."""
    proj = await store.create_project("Webhook Delivery", "Deliver webhooks reliably.")
    projects.append(proj.id)
    a = await store.create_initiative("Retry Queue", proj.id)
    b = await store.create_initiative("Dead Letter Sink", proj.id)
    inits.extend([a.id, b.id])

    await _add_confirmed_constraints(
        store, a.id,
        ["No third-party queue — reuse Postgres + Redis.",
         "At-least-once delivery; never silently drop.",
         "Backoff is capped at 1h."],
    )
    d = await store.raise_decision(
        Decision(question="at-least-once or exactly-once delivery?",
                 options=["at-least-once", "exactly-once"]),
        a.id,
    )
    await store.resolve_decision(d.id, "at-least-once", "exactly-once is impractical", "edo")
    await store._drain()  # let the best-effort embed settle (no key in test env is fine)
    return proj.id, a.id, b.id


# --- constraint 3: a sibling summary is compact but load-bearing --------------
def test_sibling_summary_is_compact(
    track_initiatives: list[str], track_projects: list[str]
):
    def go(store: SpecStore):
        async def inner():
            proj_id, a_id, b_id = await _build_project_with_two_siblings(
                store, track_projects, track_initiatives
            )
            return await store.get_project_context(proj_id, exclude=b_id)

        return inner()

    ctx = _store_run(go)
    assert ctx is not None
    assert ctx.name == "Webhook Delivery" and ctx.intent
    sib = next(s for s in ctx.siblings if s.title == "Retry Queue")
    # title + state + constraint headlines (capped) + total count + latest resolved decision
    assert sib.state == "draft"
    assert sib.constraint_count == 3
    assert len(sib.constraints) == 3  # capped at the headline limit (SIBLING_CONSTRAINT_HEADLINES)
    assert any("Postgres + Redis" in c for c in sib.constraints)
    assert sib.latest_decision and "at-least-once" in sib.latest_decision
    # the initiative in focus is excluded from its own siblings — only A remains
    assert [s.title for s in ctx.siblings] == ["Retry Queue"]


# --- a3 substrate: a project initiative's context carries its siblings --------
def test_assemble_context_includes_project_for_member(
    track_initiatives: list[str], track_projects: list[str]
):
    def go(store: SpecStore):
        async def inner():
            proj_id, a_id, b_id = await _build_project_with_two_siblings(
                store, track_projects, track_initiatives
            )
            messages = [Message(initiative_id=b_id, role="human", content="anything new I should know?")]
            return await assemble_context(store, b_id, messages=messages)

        return inner()

    ctx = _store_run(go)
    assert ctx.project is not None
    assert ctx.project.name == "Webhook Delivery"
    assert any(s.title == "Retry Queue" for s in ctx.project.siblings)


# --- a3/a5: the prompt + user message render the project block + coherence ----
def test_prompt_renders_project_and_coherence(
    track_initiatives: list[str], track_projects: list[str]
):
    def go(store: SpecStore):
        async def inner():
            proj_id, a_id, b_id = await _build_project_with_two_siblings(
                store, track_projects, track_initiatives
            )
            messages = [Message(initiative_id=b_id, role="human", content="how does this fit?")]
            return await assemble_context(store, b_id, messages=messages)

        return inner()

    ctx = _store_run(go)
    user = build_user_message(ctx)
    system = build_system_prompt(ctx.initiative.state, in_project=ctx.project is not None)

    # the user message carries the compact sibling block — title, the decision, a constraint
    assert "# PROJECT CONTEXT — Webhook Delivery" in user
    assert "Retry Queue" in user
    assert "latest decision: at-least-once" in user
    assert "Postgres + Redis" in user
    # the system prompt instructs unprompted cross-initiative coherence checking
    assert PROJECT_COHERENCE_PROMPT in system
    assert "contradicts" in system

    # with no project context, the render is empty + the coherence block is omitted (defensive)
    ctx.project = None
    assert "# PROJECT CONTEXT" not in build_user_message(ctx)
    assert PROJECT_COHERENCE_PROMPT not in build_system_prompt(ctx.initiative.state)


# --- a4: get_context is project-first, source-tagged, with a global fallback --
def test_get_context_project_first_then_global_fallback(
    track_initiatives: list[str], track_projects: list[str]
):
    outsider_text = "exactly-once webhook delivery via a third-party broker"

    def go(store: SpecStore):
        async def inner():
            proj = await store.create_project("Scoped Search", "search scoping")
            other = await store.create_project("Other Project", "the outsider's home")
            track_projects.extend([proj.id, other.id])
            sib = await store.create_initiative("In Project Sibling", proj.id)
            outsider = await store.create_initiative("Outside Initiative", other.id)
            caller = await store.create_initiative("The Caller", proj.id)
            track_initiatives.extend([sib.id, outsider.id, caller.id])

            # one resolved+embedded decision inside the project, one outside it
            din = await store.raise_decision(
                Decision(question="reuse Postgres for the project's retry queue?",
                         options=["yes", "no"]),
                sib.id,
            )
            await store.resolve_decision(din.id, "yes", "no third-party queue", "edo")
            await store.embed_decision(din.id)
            await store.pg.execute("UPDATE initiatives SET state = 'complete' WHERE id = $1", sib.id)
            dout = await store.raise_decision(
                Decision(question=outsider_text, options=["broker", "db"]), outsider.id
            )
            await store.resolve_decision(dout.id, "broker", "fastest path", "edo")
            await store.embed_decision(dout.id)
            await store.pg.execute("UPDATE initiatives SET state = 'complete' WHERE id = $1", outsider.id)
            await store._drain()

            scoped = await store.get_context(outsider_text, limit=8, project_id=proj.id)
            return proj.id, sib.id, caller.id, outsider.id, scoped

        return inner()

    proj_id, sib_id, caller_id, outsider_id, scoped = _store_run(go, embedder=FakeEmbedder())

    # the in-project sibling is returned and tagged project; project hits precede global ones
    project_hits = [h for h in scoped if h.scope == "project"]
    global_hits = [h for h in scoped if h.scope == "global"]
    assert any(h.initiative_id == sib_id for h in project_hits)
    assert scoped[0].scope == "project"  # project-first
    # the project was thin, so the fallback reached OUTSIDE it — and tagged those global.
    # FakeEmbedder uses hash-based random vectors, so we cannot assert which specific
    # external decision ranks highest — only that the fallback ran and tagged its hits "global"
    # and that none of the global hits came from within the project.
    assert global_hits, "the global fallback returned nothing"
    in_project_ids = {sib_id, caller_id}
    assert not any(h.initiative_id in in_project_ids for h in global_hits)
    assert all(h.scope == "global" for h in global_hits)


# --- a6: a unit briefing in a project carries sibling constraints + decisions -
def test_guidance_includes_project_context(
    track_initiatives: list[str], track_projects: list[str]
):
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            proj_id, a_id, b_id = await _build_project_with_two_siblings(
                store, track_projects, track_initiatives
            )
            unit = await store.create_unit(
                WorkUnit(spec_id=b_id, title="wire the retry scheduler",
                         scope="re-enqueue failed deliveries with capped backoff")
            )
            guidance = await generate_guidance(store, unit.id, llm=fake)
            return guidance

        return inner()

    guidance = _store_run(go, embedder=FakeEmbedder())
    assert guidance.briefing  # the Advisor synthesised a briefing
    # a6 — the sibling's constraints + decision were put in front of the briefing Advisor
    user = fake.calls[0]["user"]
    assert "# PROJECT CONTEXT" in user
    assert "Retry Queue" in user  # the sibling initiative
    assert "Postgres + Redis" in user  # a sibling confirmed constraint
    assert "at-least-once" in user  # the sibling's resolved decision
    assert fake.calls[0]["schema_name"] == "guidance"


# --- a9: a project-rail turn is scoped to the whole project (browser-local; unpersisted) ------
def test_project_advisor_turn_grounds_in_whole_project(
    track_initiatives: list[str], track_projects: list[str]
):
    # Conversations are browser-local now (spec uvama): advise_project returns the Advisor's reply
    # Message and persists nothing. The grounding (whole-project scope) is unchanged.
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            proj_id, _a, _b = await _build_project_with_two_siblings(
                store, track_projects, track_initiatives
            )
            reply, proposed = await advise_project(
                store, proj_id, "how is this project going?", llm=fake
            )
            return proj_id, reply, proposed

        return inner()

    proj_id, reply, proposed = _store_run(go, embedder=FakeEmbedder())
    # the reply is PROJECT-owned (no initiative owner), unpersisted
    assert reply.project_id == proj_id and reply.initiative_id is None
    assert reply.role == "advisor" and reply.content
    # ordinary strategic conversation -> no synthesised initiative (BD-1 u3)
    assert proposed is None

    # the Advisor was scoped to the WHOLE project (every initiative), in strategic mode
    user, system = fake.calls[0]["user"], fake.calls[0]["system"]
    assert "# PROJECT — Webhook Delivery" in user
    assert "Retry Queue" in user  # an initiative summary is present
    assert "whole project" in system.lower()
    assert fake.calls[0]["schema_name"] == "advisor_reply"


# --- BD-1 u3: the project rail can synthesise a discussion into a PROPOSED initiative ----------
def test_project_rail_synthesises_a_proposed_initiative():
    # When the conversation crystallises into a concrete new initiative, the Advisor returns it as
    # proposed_initiative alongside the reply — the signal the rail turns into a 'Create initiative
    # from this' action. DB-free: _converse_project takes the context directly.
    proj = ProjectContext(
        project_id="proj_x", name="Webhook Delivery", prefix="WD", intent="reliable delivery"
    )
    desc = "Add a dead-letter queue so webhooks that fail every retry are captured for replay, not lost."
    fake = FakeLLM(proposed_initiative=desc)

    reply, proposed = asyncio.run(_converse_project(proj, [], [], fake))

    assert reply  # the normal rail message is still there
    assert proposed == desc  # the synthesised description is surfaced verbatim
    assert fake.calls[0]["schema_name"] == "advisor_reply"
    # the synthesis instruction is in the prompt (correction-over-authoring framing)
    assert "proposed_initiative" in fake.calls[0]["system"]


def test_project_rail_no_synthesis_in_ordinary_conversation():
    # Most turns aren't an initiative proposal: proposed_initiative stays None, so no action shows.
    proj = ProjectContext(project_id="proj_x", name="Webhook Delivery")
    reply, proposed = asyncio.run(_converse_project(proj, [], [], FakeLLM()))
    assert reply and proposed is None


def test_project_rail_blank_synthesis_is_treated_as_none():
    # A whitespace/empty proposed_initiative must not surface a spurious action.
    proj = ProjectContext(project_id="proj_x", name="Webhook Delivery")
    reply, proposed = asyncio.run(_converse_project(proj, [], [], FakeLLM(proposed_initiative="   ")))
    assert reply and proposed is None
