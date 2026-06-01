"""u1 — work_units table, model, and state machine (spec 0003).

Covers a1 (a unit persists with its fields as status=proposed) and a2 (transitions
follow the fixed machine; illegal jumps are rejected). The state machine is pure, so
it's tested directly on the model; persistence goes through SpecStore against the real
docker-compose Postgres + Redis (no HTTP surface yet — endpoints arrive in u3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from fastapi.testclient import TestClient
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.exceptions import InvalidTransition
from app.models import CriterionResult, Decision, Submission, Verdict, WorkUnit
from app.store import SpecStore


def _store_run(fn: Callable[[SpecStore], Awaitable[object]]) -> object:
    """Run one store interaction against the real PG/Redis, then tear the clients down."""
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis))
        finally:
            await pg.close()
            await redis.aclose()

    return asyncio.run(go())


def _spec_row(client: TestClient, iid: str) -> None:
    """A unit's spec_id FKs to specs(initiative_id), so the spec row must exist first."""
    r = client.put(f"/specs/{iid}", json={"initiative_id": iid, "title": "T", "version": 0})
    assert r.status_code == 200, r.text


# --- a1 -----------------------------------------------------------------------
def test_create_unit_persists_as_proposed(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    unit = WorkUnit(
        spec_id=iid,
        title="work_units table + model",
        scope="migration, model, state-machine validation",
        criterion_ids=["item_aaa", "item_bbb"],
    )
    assert unit.status == "proposed"  # born proposed, not workable yet

    _store_run(lambda s: s.create_unit(unit))
    got = _store_run(lambda s: s.get_unit(unit.id))

    assert got is not None
    assert got.spec_id == iid
    assert got.title == "work_units table + model"
    assert got.scope == "migration, model, state-machine validation"
    assert got.criterion_ids == ["item_aaa", "item_bbb"]
    assert got.status == "proposed"


# --- a2 -----------------------------------------------------------------------
def test_happy_path_transitions():
    u = WorkUnit(spec_id="x", title="t", scope="s")
    for target in ("ready", "in_progress", "in_verification", "done"):
        u.transition(target)
    assert u.status == "done"


def test_blocked_and_changes_requested_paths():
    u = WorkUnit(spec_id="x", title="t", scope="s", status="in_progress")
    u.transition("blocked_on_decision")
    u.transition("in_progress")  # a9 — decision resolved, resume
    u.transition("in_verification")
    u.transition("in_progress")  # a7 — changes_requested verdict lands back here
    u.transition("in_verification")
    u.transition("done")


def test_illegal_transitions_are_rejected():
    # skipping a state
    with pytest.raises(InvalidTransition):
        WorkUnit(spec_id="x", title="t", scope="s").transition("in_progress")
    # ready -> done jumps the middle
    with pytest.raises(InvalidTransition):
        WorkUnit(spec_id="x", title="t", scope="s", status="ready").transition("done")
    # done is terminal
    with pytest.raises(InvalidTransition):
        WorkUnit(spec_id="x", title="t", scope="s", status="done").transition("in_progress")


def test_transition_persists_status_column(
    client: TestClient, make_initiative: Callable[[], str]
):
    # The promoted status column must track the payload, so list_units can filter on it.
    iid = make_initiative()
    _spec_row(client, iid)
    unit = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(unit))

    async def confirm(s: SpecStore) -> WorkUnit:
        u = await s.get_unit(unit.id)
        u.transition("ready")
        return await s.save_unit(u)

    saved = _store_run(confirm)
    assert saved.status == "ready"

    col = _store_run(
        lambda s: s.pg.fetchval("SELECT status FROM work_units WHERE id = $1", unit.id)
    )
    assert col == "ready"


# --- u2: executor tools (propose / list / progress / submit / verification) ---
async def _to_in_progress(s: SpecStore, unit_id: str) -> WorkUnit:
    u = await s.get_unit(unit_id)
    u.transition("ready")
    u.transition("in_progress")
    return await s.save_unit(u)


# a3 — list_units returns a spec's units, optionally filtered by status.
def test_list_units_filters_by_status(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    a = WorkUnit(spec_id=iid, title="a", scope="s")
    b = WorkUnit(spec_id=iid, title="b", scope="s")
    _store_run(lambda s: s.create_unit(a))
    _store_run(lambda s: s.create_unit(b))
    _store_run(lambda s: _to_in_progress(s, b.id))  # b leaves 'proposed'

    assert {u.id for u in _store_run(lambda s: s.list_units(iid))} == {a.id, b.id}
    assert [u.id for u in _store_run(lambda s: s.list_units(iid, "proposed"))] == [a.id]
    assert [u.id for u in _store_run(lambda s: s.list_units(iid, "in_progress"))] == [b.id]


# claim — the executor starts a confirmed unit (ready -> in_progress); only ready units.
def test_claim_unit_ready_to_in_progress(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))

    # cannot claim while still proposed
    with pytest.raises(InvalidTransition):
        _store_run(lambda s: s.claim_unit(u.id))

    _store_run(lambda s: s.confirm_unit(u.id))  # proposed -> ready
    claimed = _store_run(lambda s: s.claim_unit(u.id))
    assert claimed.status == "in_progress"


# a5 — report_progress sets the unit's note.
def test_report_progress_sets_note(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))

    saved = _store_run(lambda s: s.report_progress(u.id, "halfway through the migration"))
    assert saved.progress_note == "halfway through the migration"
    assert _store_run(lambda s: s.get_unit(u.id)).progress_note == "halfway through the migration"


# a6 — submit_for_verification moves to in_verification and stores the submission.
def test_submit_moves_to_in_verification(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))
    _store_run(lambda s: _to_in_progress(s, u.id))

    sub = Submission(
        summary="built the table + model",
        criteria_results=[
            CriterionResult(criterion_id="item_a1", result="pass", evidence="test passes")
        ],
    )
    saved = _store_run(lambda s: s.submit_for_verification(u.id, sub))
    assert saved.status == "in_verification"
    assert saved.submission.summary == "built the table + model"
    assert saved.submission.criteria_results[0].result == "pass"


def test_submit_requires_a_criterion_result(
    client: TestClient, make_initiative: Callable[[], str]
):
    # constraint 4 — a submission with no criterion results is rejected, and nothing moves.
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))
    _store_run(lambda s: _to_in_progress(s, u.id))

    empty = Submission(summary="nothing to show", criteria_results=[])
    with pytest.raises(ValueError):
        _store_run(lambda s: s.submit_for_verification(u.id, empty))
    assert _store_run(lambda s: s.get_unit(u.id)).status == "in_progress"  # unchanged


# a8 — get_verification is pending until a human verdict lands, then returns it.
def test_get_verification_pending_then_verdict(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))
    assert _store_run(lambda s: s.get_verification(u.id)) is None  # pending

    async def land_verdict(s: SpecStore) -> WorkUnit:
        # u3 writes the verdict via the human endpoint; here we exercise the read path.
        x = await s.get_unit(u.id)
        x.verdict = Verdict(verdict="approved", feedback="looks right", decided_by="edo")
        return await s.save_unit(x)

    _store_run(land_verdict)
    v = _store_run(lambda s: s.get_verification(u.id))
    assert v is not None and v.verdict == "approved" and v.feedback == "looks right"


def test_mcp_server_imports_with_unit_tools():
    # the @mcp.tool() decorators run at import; this catches wiring / signature errors.
    from app import mcp_server

    assert mcp_server.mcp is not None


# --- u3: human confirm + verdict + decision linking (HTTP surface) ------------
async def _advance(s: SpecStore, unit_id: str, *targets: str) -> WorkUnit:
    u = await s.get_unit(unit_id)
    for t in targets:
        u.transition(t)
    return await s.save_unit(u)


# a4 — a human confirms a proposed unit to ready; only proposed units can be confirmed.
def test_confirm_unit_proposed_to_ready(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))

    r = client.post(f"/units/{u.id}/confirm")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    # a second confirm is illegal (ready -> ready is not a transition)
    assert client.post(f"/units/{u.id}/confirm").status_code == 422


def test_confirm_missing_unit_404(client: TestClient):
    assert client.post("/units/unit_missing/confirm").status_code == 404


# a7 — approved -> done; changes_requested -> in_progress with feedback.
def test_verdict_approved_moves_to_done(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))
    _store_run(lambda s: _advance(s, u.id, "ready", "in_progress", "in_verification"))

    r = client.post(f"/units/{u.id}/verdict", json={"verdict": "approved", "feedback": "great"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done"
    assert body["verdict"]["verdict"] == "approved"
    assert body["verdict"]["feedback"] == "great"


def test_verdict_changes_requested_returns_to_in_progress(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))
    _store_run(lambda s: _advance(s, u.id, "ready", "in_progress", "in_verification"))

    r = client.post(
        f"/units/{u.id}/verdict", json={"verdict": "changes_requested", "feedback": "fix the FK"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_progress"
    assert body["verdict"]["feedback"] == "fix the FK"


def test_verdict_only_on_a_submitted_unit(
    client: TestClient, make_initiative: Callable[[], str]
):
    # no verdict source for unsubmitted work — a verdict on a proposed unit is rejected.
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))
    assert client.post(f"/units/{u.id}/verdict", json={"verdict": "approved"}).status_code == 422


# a9 — resolving a decision a unit is blocked on resumes the unit to in_progress.
def test_resolving_decision_resumes_blocked_unit(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _spec_row(client, iid)
    u = WorkUnit(spec_id=iid, title="u", scope="s")
    _store_run(lambda s: s.create_unit(u))
    _store_run(lambda s: _advance(s, u.id, "ready", "in_progress"))

    async def raise_and_block(s: SpecStore) -> Decision:
        d = await s.raise_decision(Decision(question="q?", options=["a", "b"]), iid)
        await s.block_on_decision(u.id, d.id)
        return d

    d = _store_run(raise_and_block)
    assert _store_run(lambda s: s.get_unit(u.id)).status == "blocked_on_decision"

    # resolve via the existing rail endpoint (the human escalation flow)
    r = client.post(f"/decisions/{d.id}/resolve", json={"chosen": "a", "rationale": "because"})
    assert r.status_code == 200, r.text

    resumed = _store_run(lambda s: s.get_unit(u.id))
    assert resumed.status == "in_progress"
    assert resumed.blocked_on is None
