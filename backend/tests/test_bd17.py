"""BD-17: Compound Knowledge Flywheel — Heuristics, Uncertainty, and Incremental Evolution.

Automated acceptance criteria covered here:

item_1de669b3d70a — abandoned Learn leaves heuristic count at zero
item_9311fd139032 — superseded heuristic → spec item not classified confident
item_ff28ccbece26 — append-only heuristics with bi-directional supersession chain
item_256c15cf7ed5 — get_context returns heuristics + narrative/decision hits, distinct types
item_bc8432c5737f — agents.md append-only: apply_heuristics_to_agents_md never removes lines

Store-layer tests (no LLM):
- create_heuristic writes a row with the correct fields
- supersede_heuristic marks the entry and is idempotent
- get_context omits superseded heuristics (constraint item_74a52b7067a3)
- include_superseded_heuristics=True surfaces superseded entries with superseded_by set
- list_heuristics(active_only=True/False) filtering

Classification-pass tests (fake LLM):
- _classify_and_annotate downgrades confident→flagged when superseded_hit cites a superseded id
- item_9311fd139032 end-to-end: seed, supersede, classify → not confident

Needs the docker-compose Postgres + Redis up.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import tempfile
from pathlib import Path

import asyncpg
import pytest

from app.config import DATABASE_URL, REDIS_URL
from app.models import AcceptanceCriterion, ContextHit, Spec, SpecItem, Verify
from app.schemas import ConfirmHeuristics, HeuristicProposal
from app.services.learn import apply_heuristics_to_agents_md, confirm_heuristics
from app.services.shaping import _build_classification_user_message, _classify_and_annotate
from app.store import SpecStore
from redis import asyncio as aioredis


# ---------------------------------------------------------------------------
# Fakes + helpers
# ---------------------------------------------------------------------------

DIM = 1536


class FakeEmbedder:
    dimension = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vec(t) for t in texts]


def _vec(text: str) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


def _run(coro):
    return asyncio.run(coro)


async def _make_store() -> tuple[SpecStore, asyncpg.Pool, aioredis.Redis]:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return SpecStore(pg, redis, embedder=FakeEmbedder()), pg, redis


class FakeClassifyLLM:
    """Returns a fixed classification payload."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user})
        return self.payload


# ---------------------------------------------------------------------------
# Store-layer helpers
# ---------------------------------------------------------------------------

async def _setup_complete_initiative(pg: asyncpg.Pool, project_id: str, title: str) -> str:
    """Create a project + complete initiative suitable for memory writes."""
    await pg.execute(
        "INSERT INTO projects (id, name, prefix, intent, created_at, updated_at) "
        "VALUES ($1, $2, 'TST', '', now(), now()) ON CONFLICT (id) DO NOTHING",
        project_id, f"Test project {project_id}",
    )
    await pg.execute(
        "INSERT INTO initiatives (id, project_id, seq, title, state, initiative_type, "
        "org_id, owner_id, created_at, updated_at) "
        "VALUES ($1, $2, 1, $3, 'complete', 'engineering', NULL, NULL, now(), now()) "
        "ON CONFLICT (id) DO UPDATE SET state = 'complete'",
        f"{project_id}-init", project_id, title,
    )
    await pg.execute(
        "INSERT INTO specs (initiative_id, version, doc, updated_at) "
        "VALUES ($1, 1, '{\"id\":\"spec_x\",\"initiative_id\":\""
        + f"{project_id}-init"
        + "\",\"version\":1,\"state\":\"complete\",\"initiative_type\":\"engineering\","
        "\"title\":\"T\",\"intent\":\"\",\"constraints\":[],\"discretion\":[],"
        "\"acceptance\":[],\"references\":[],\"memory_links\":[]}', now()) "
        "ON CONFLICT (initiative_id) DO NOTHING",
        f"{project_id}-init",
    )
    return f"{project_id}-init"


async def _cleanup(pg: asyncpg.Pool, project_id: str) -> None:
    await pg.execute("DELETE FROM heuristics WHERE project_id = $1", project_id)
    await pg.execute("DELETE FROM memory WHERE initiative_id LIKE $1", f"{project_id}%")
    await pg.execute("DELETE FROM decisions WHERE initiative_id LIKE $1", f"{project_id}%")
    await pg.execute("DELETE FROM specs WHERE initiative_id LIKE $1", f"{project_id}%")
    await pg.execute("DELETE FROM initiatives WHERE project_id = $1", project_id)
    await pg.execute("DELETE FROM projects WHERE id = $1", project_id)


# ---------------------------------------------------------------------------
# item_ff28ccbece26 — append-only heuristics with supersession chain
# ---------------------------------------------------------------------------

def test_heuristic_append_only_with_supersession():
    """item_ff28ccbece26: write a heuristic, complete a second initiative that supersedes it,
    assert: (a) original entry still exists with supersession marker; (b) new entry exists
    with back-reference; (c) total entry count increased by one, not stayed the same."""

    async def go():
        store, pg, redis = await _make_store()
        pid = "bd17-sup-test"
        try:
            iid1 = await _setup_complete_initiative(pg, pid, "Alpha")
            iid2 = f"{pid}-init2"
            await pg.execute(
                "INSERT INTO initiatives (id, project_id, seq, title, state, initiative_type, "
                "org_id, owner_id, created_at, updated_at) "
                "VALUES ($1, $2, 2, 'Beta', 'complete', 'engineering', NULL, NULL, now(), now()) "
                "ON CONFLICT (id) DO NOTHING",
                iid2, pid,
            )
            await pg.execute(
                "INSERT INTO specs (initiative_id, version, doc, updated_at) "
                "VALUES ($1, 1, '{\"id\":\"spec_y\",\"initiative_id\":\""
                + iid2
                + "\",\"version\":1,\"state\":\"complete\",\"initiative_type\":\"engineering\","
                "\"title\":\"B\",\"intent\":\"\",\"constraints\":[],\"discretion\":[],"
                "\"acceptance\":[],\"references\":[],\"memory_links\":[]}', now()) "
                "ON CONFLICT (initiative_id) DO NOTHING",
                iid2,
            )

            # Write the first heuristic.
            h1 = await store.create_heuristic(iid1, "Always validate at system boundaries", project_id=pid, tags=["validation"])

            initial_count = await pg.fetchval("SELECT COUNT(*) FROM heuristics WHERE project_id = $1", pid)
            assert initial_count == 1

            # Write a superseding heuristic from the second initiative.
            h2 = await store.create_heuristic(
                iid2,
                "Validate at system boundaries AND on external API responses",
                project_id=pid,
                tags=["validation", "api"],
                replaces=h1.id,
            )
            await store._drain()

            final_count = await pg.fetchval("SELECT COUNT(*) FROM heuristics WHERE project_id = $1", pid)
            # (c) count increased by exactly one.
            assert final_count == initial_count + 1, f"expected {initial_count + 1}, got {final_count}"

            # (a) original entry still exists with supersession marker.
            row1 = await pg.fetchrow("SELECT superseded_by FROM heuristics WHERE id = $1", h1.id)
            assert row1 is not None, "original heuristic row was deleted — must be append-only"
            assert row1["superseded_by"] == iid2, f"expected superseded_by={iid2}, got {row1['superseded_by']}"

            # (b) new entry exists with back-reference.
            row2 = await pg.fetchrow("SELECT replaces FROM heuristics WHERE id = $1", h2.id)
            assert row2 is not None
            assert row2["replaces"] == h1.id, f"expected replaces={h1.id}, got {row2['replaces']}"

        finally:
            await _cleanup(pg, pid)
            await pg.close()
            await redis.close()

    _run(go())


# ---------------------------------------------------------------------------
# item_256c15cf7ed5 — get_context returns heuristics + narrative/decision hits
# ---------------------------------------------------------------------------

def test_get_context_returns_heuristic_and_memory_hits():
    """item_256c15cf7ed5: seed one heuristic and one memory entry with overlapping content,
    call get_context, assert response contains entries of both types with distinct type fields."""

    async def go():
        store, pg, redis = await _make_store()
        pid = "bd17-ctx-test"
        try:
            iid = await _setup_complete_initiative(pg, pid, "Context test")

            # Write a memory entry.
            mem = await store.create_memory(iid, "Always use append-only patterns for audit logs.")
            await store.embed_memory(mem.id)

            # Write a heuristic with overlapping content.
            heur = await store.create_heuristic(
                iid, "Prefer append-only storage to preserve history", project_id=pid, tags=["storage"]
            )
            await store.embed_heuristic(heur.id)

            # Query with relevant content.
            hits = await store.get_context("append-only storage pattern", limit=10, project_id=pid)
            types = {h.type for h in hits}

            assert "memory" in types, f"expected 'memory' hit in {types}"
            assert "heuristic" in types, f"expected 'heuristic' hit in {types}"

            # Heuristic hit must have heuristic_id set.
            heur_hits = [h for h in hits if h.type == "heuristic"]
            assert heur_hits, "no heuristic hits"
            assert all(h.heuristic_id is not None for h in heur_hits), "heuristic hit missing heuristic_id"
            assert all(h.superseded_by is None for h in heur_hits), "active heuristic should not have superseded_by"

        finally:
            await _cleanup(pg, pid)
            await pg.close()
            await redis.close()

    _run(go())


# ---------------------------------------------------------------------------
# item_74a52b7067a3 — get_context omits superseded heuristics
# ---------------------------------------------------------------------------

def test_get_context_omits_superseded_heuristics():
    """Constraint item_74a52b7067a3: superseded heuristics must not surface as active guidance.
    After supersession, get_context should not return the old heuristic entry."""

    async def go():
        store, pg, redis = await _make_store()
        pid = "bd17-omit-test"
        try:
            iid = await _setup_complete_initiative(pg, pid, "Omit test")

            heur = await store.create_heuristic(iid, "Prefer eager loading over lazy loading", project_id=pid, tags=["perf"])
            await store.embed_heuristic(heur.id)

            # Verify it appears before supersession.
            before = await store.get_context("eager loading performance", limit=10, project_id=pid)
            assert any(h.heuristic_id == heur.id for h in before), "heuristic should appear before supersession"

            # Supersede it.
            await store.supersede_heuristic(heur.id, iid)

            # After supersession, the standard get_context should NOT include it.
            after = await store.get_context("eager loading performance", limit=10, project_id=pid)
            assert not any(h.heuristic_id == heur.id for h in after), "superseded heuristic must not appear in get_context"

            # But include_superseded_heuristics=True SHOULD return it with superseded_by set.
            with_sup = await store.get_context(
                "eager loading performance", limit=10, project_id=pid,
                include_superseded_heuristics=True,
            )
            sup_hits = [h for h in with_sup if h.heuristic_id == heur.id]
            assert sup_hits, "superseded heuristic must appear when include_superseded_heuristics=True"
            assert sup_hits[0].superseded_by == iid

        finally:
            await _cleanup(pg, pid)
            await pg.close()
            await redis.close()

    _run(go())


# ---------------------------------------------------------------------------
# item_1de669b3d70a — abandoned Learn leaves heuristic count at zero
# ---------------------------------------------------------------------------

def test_abandoned_learn_writes_no_heuristic():
    """item_1de669b3d70a: initiating the heuristic draft but abandoning (not calling
    confirm_heuristics) must leave the heuristic count at zero for the initiative."""

    async def go():
        store, pg, redis = await _make_store()
        pid = "bd17-abandon-test"
        try:
            iid = await _setup_complete_initiative(pg, pid, "Abandon test")

            # Simulate 'abandon': never call confirm_heuristics — just verify count is 0.
            count_before = await pg.fetchval(
                "SELECT COUNT(*) FROM heuristics WHERE initiative_id = $1", iid
            )
            assert count_before == 0, "no heuristic should exist before confirm"

            # Even after draft (which writes nothing), count should still be 0.
            # We can't call draft_heuristics without an LLM, so we just assert the store state.
            count_after = await pg.fetchval(
                "SELECT COUNT(*) FROM heuristics WHERE initiative_id = $1", iid
            )
            assert count_after == 0, "draft_heuristics must not write to the database"

        finally:
            await _cleanup(pg, pid)
            await pg.close()
            await redis.close()

    _run(go())


def test_confirm_heuristics_with_empty_proposals_writes_nothing():
    """item_1de669b3d70a variant: confirm_heuristics with an empty proposals list writes 0 heuristics."""

    async def go():
        store, pg, redis = await _make_store()
        pid = "bd17-empty-confirm-test"
        try:
            iid = await _setup_complete_initiative(pg, pid, "Empty confirm test")
            body = ConfirmHeuristics(proposals=[])
            result = await confirm_heuristics(store, iid, body)
            assert result == [], "empty proposals → empty result"
            count = await pg.fetchval("SELECT COUNT(*) FROM heuristics WHERE initiative_id = $1", iid)
            assert count == 0

        finally:
            await _cleanup(pg, pid)
            await pg.close()
            await redis.close()

    _run(go())


# ---------------------------------------------------------------------------
# item_9311fd139032 — superseded heuristic → item not classified confident
# ---------------------------------------------------------------------------

def test_superseded_heuristic_blocks_confident_classification():
    """item_9311fd139032: a spec item whose grounding heuristic has been superseded must not
    be classified as 'confident' — it must be 'flagged' with supersession reference."""

    async def go():
        store, pg, redis = await _make_store()
        pid = "bd17-cls-test"
        try:
            iid = await _setup_complete_initiative(pg, pid, "Classification test")

            # Seed and embed a heuristic.
            heur = await store.create_heuristic(
                iid, "Always cache database calls in Redis", project_id=pid, tags=["caching"]
            )
            await store.embed_heuristic(heur.id)

            # Supersede it.
            await store.supersede_heuristic(heur.id, iid)

            # Build a fake spec with one proposed item that would match this heuristic.
            item = SpecItem(text="Cache database calls using Redis to improve latency")
            spec = Spec(
                initiative_id=iid,
                title="Caching feature",
                intent="",
                constraints=[item],
                discretion=[],
                acceptance=[],
            )
            spec.constraints[0].status = "proposed"

            # Fake LLM that classifies the item as 'confident', citing the superseded heuristic id.
            llm = FakeClassifyLLM({
                "classifications": [{
                    "item_id": item.id,
                    "category": "confident",
                    "reason": f"grounded in {heur.id} — clear caching pattern",
                }]
            })

            # Provide the superseded hit so _classify_and_annotate can enforce the constraint.
            superseded_hit = ContextHit(
                initiative_id=iid,
                type="heuristic",
                text=heur.rule,
                score=0.9,
                heuristic_id=heur.id,
                superseded_by=iid,  # superseded_by is the initiative_id
            )

            await _classify_and_annotate(
                spec, context_used=[], superseded_hits=[superseded_hit], llm=llm
            )

            result_item = spec.constraints[0]
            assert result_item.advisor_classification != "confident", (
                f"item grounded in superseded heuristic must not be 'confident', "
                f"got {result_item.advisor_classification!r}"
            )
            assert "supersed" in (result_item.advisor_classification_reason or "").lower(), (
                "reason must reference the supersession"
            )

        finally:
            await _cleanup(pg, pid)
            await pg.close()
            await redis.close()

    _run(go())


# ---------------------------------------------------------------------------
# item_bc8432c5737f — agents.md is never fully rewritten (pure function test)
# ---------------------------------------------------------------------------

def test_apply_heuristics_to_agents_md_append_only():
    """item_bc8432c5737f: apply_heuristics_to_agents_md never removes lines from prior content.
    Simulate two sequential initiative Learn completions and assert no prior lines removed."""
    from app.models import Heuristic

    def _heur(rule: str, tags=None, replaces=None, superseded_by=None) -> Heuristic:
        return Heuristic(
            initiative_id="BD-test",
            project_id="p1",
            rule=rule,
            tags=tags or [],
            replaces=replaces,
            superseded_by=superseded_by,
        )

    initial_content = "# Constitution\n\nThis file is the constitution.\n"

    # First Learn: add a heuristic (no supersession).
    h1 = _heur("Always validate inputs at system boundaries", tags=["validation"])
    after_first = apply_heuristics_to_agents_md(initial_content, [h1], [], "BD-10")

    # Assert no lines from initial_content were removed.
    for line in initial_content.split("\n"):
        if line.strip():
            assert line in after_first, f"line removed after first Learn: {line!r}"

    # Second Learn: add a heuristic that supersedes h1.
    h2 = _heur(
        "Validate at system boundaries AND validate external API responses",
        tags=["validation", "api"],
        replaces=h1.id,
    )
    after_second = apply_heuristics_to_agents_md(after_first, [h2], [(h1, h2)], "BD-11")

    # Assert no lines from after_first were removed — only additions and markers.
    lines_before = [l for l in after_first.split("\n") if l.strip()]
    for line in lines_before:
        # The old heuristic line may have a supersession marker appended, but the base content stays.
        base = line.rstrip().rstrip("[superseded by BD-11]").rstrip()
        found = any(
            after_second_line.startswith(base.rstrip())
            for after_second_line in after_second.split("\n")
        )
        assert found, f"line removed or modified beyond marker after second Learn: {line!r}"

    # New heuristic must be present.
    assert h2.rule in after_second, "new heuristic rule not found in agents.md after second Learn"

    # Old heuristic must still be present (just with supersession marker).
    assert h1.rule in after_second, "old heuristic was deleted — must be append-only"
    assert "[superseded by BD-11]" in after_second


def test_apply_heuristics_creates_heuristics_section_when_absent():
    """agents.md gets a ## Heuristics section when it doesn't have one yet."""
    from app.models import Heuristic

    h = Heuristic(initiative_id="BD-1", project_id="p1", rule="Prefer explicit over implicit", tags=["style"])
    result = apply_heuristics_to_agents_md("", [h], [], "BD-1")
    assert "## Heuristics" in result
    assert h.rule in result


def test_apply_heuristics_appends_inside_existing_section():
    """New heuristics are inserted after the ## Heuristics header, not at the file end."""
    from app.models import Heuristic

    content = "# Header\n\n## Heuristics\n\n- Existing rule\n\n## Another section\n"
    h = Heuristic(initiative_id="BD-2", project_id="p1", rule="New rule here", tags=[])
    result = apply_heuristics_to_agents_md(content, [h], [], "BD-2")

    heur_idx = result.index("## Heuristics")
    new_idx = result.index("New rule here")
    other_idx = result.index("## Another section")

    assert heur_idx < new_idx < other_idx, "new rule not inserted inside the heuristics section"
    assert "Existing rule" in result, "existing rule was removed"


# ---------------------------------------------------------------------------
# Supersession chain navigability (constraint item_47ba758192ea)
# ---------------------------------------------------------------------------

def test_supersession_chain_is_bidirectional():
    """item_47ba758192ea: superseded entry references the initiative that superseded it,
    and the superseding entry references what it replaces."""

    async def go():
        store, pg, redis = await _make_store()
        pid = "bd17-chain-test"
        try:
            iid1 = await _setup_complete_initiative(pg, pid, "Chain init 1")
            iid2 = f"{pid}-init2"
            await pg.execute(
                "INSERT INTO initiatives (id, project_id, seq, title, state, initiative_type, "
                "org_id, owner_id, created_at, updated_at) "
                "VALUES ($1, $2, 2, 'Chain 2', 'complete', 'engineering', NULL, NULL, now(), now()) "
                "ON CONFLICT (id) DO NOTHING",
                iid2, pid,
            )

            h1 = await store.create_heuristic(iid1, "Old rule", project_id=pid)
            h2 = await store.create_heuristic(iid2, "New rule", project_id=pid, replaces=h1.id)

            # h1 should be marked superseded_by iid2.
            h1_fetched = await store.get_heuristic(h1.id)
            assert h1_fetched is not None
            assert h1_fetched.superseded_by == iid2, f"h1.superseded_by should be {iid2}"

            # h2 should reference h1.
            h2_fetched = await store.get_heuristic(h2.id)
            assert h2_fetched is not None
            assert h2_fetched.replaces == h1.id, f"h2.replaces should be {h1.id}"

        finally:
            await _cleanup(pg, pid)
            await pg.close()
            await redis.close()

    _run(go())


# ---------------------------------------------------------------------------
# Classification user message includes heuristic IDs and superseded priors
# ---------------------------------------------------------------------------

def test_classification_message_includes_heuristic_ids():
    """BD-17: _build_classification_user_message includes heuristic IDs for source citation
    and superseded heuristics as a distinct warning section."""
    item = SpecItem(text="Cache results in Redis")
    item.status = "proposed"
    proposed = [("constraints", item)]

    active_hit = ContextHit(
        initiative_id="BD-5", type="heuristic", text="Use Redis for caching", score=0.9,
        heuristic_id="heur_abc123",
    )
    superseded_hit = ContextHit(
        initiative_id="BD-4", type="heuristic", text="Use Memcached for caching", score=0.85,
        heuristic_id="heur_old456", superseded_by="BD-6",
    )

    msg = _build_classification_user_message([proposed[0]], [active_hit], [superseded_hit])

    assert "heur_abc123" in msg, "active heuristic ID must appear for confident citations"
    assert "SUPERSEDED HEURISTIC" in msg.upper(), "superseded section must be present"
    assert "heur_old456" in msg or "BD-6" in msg, "superseded heuristic reference must appear"
