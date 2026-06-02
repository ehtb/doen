"""BD-13: Discretion Auditor, Structured Rationale, and Steering-Ratio Awareness.

Integration tests covering the store/service layer without LLM calls:

a1 — agent_resolve_decision saves as 'resolved', no attention item (Redis escalation skipped).
a2 — count_human_resolved_decisions excludes agent-resolved decisions.
a3 — agent-resolved decisions appear in list_decisions('resolved') for the decision log.
a4 — learn submit_learn gates memory write — no rationale without confirm.
a5 — steering-ratio threshold: count_human_resolved_decisions counts human-only.
a6 — build_system_prompt includes STEERING_RATIO_NOTE when count >= threshold.
a7 — discretion_auditor.audit_decision: hallucinated item id is rejected (within_discretion=False).
a8 — discretion_auditor: empty discretion list → within_discretion=False without LLM call.

Tests requiring a real LLM (a1/a2 from the spec's verify.kind=test for the MCP path, and the
Advisor steering-ratio end-to-end) are marked behavioral — covered by the human_judgment criterion
and the /verify skill. The pure store + service tests run fully offline.

Needs the docker-compose Postgres + Redis up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import DATABASE_URL, REDIS_URL
from app.models import Decision, SpecItem
from app.schemas import RationaleClaim
from app.services.advisor import STEERING_RATIO_THRESHOLD, build_system_prompt
from app.services.discretion_auditor import AuditResult, audit_decision
from app.store import SpecStore
from redis import asyncio as aioredis


def _run(coro) -> object:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_store() -> SpecStore:
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return SpecStore(pg, redis)


async def _agent_resolve(iid: str, q: str, opts: list[str], disc_item_id: str) -> str:
    store = await _make_store()
    d = Decision(question=q, options=opts)
    saved = await store.agent_resolve_decision(
        d, iid,
        chosen=opts[0],
        rationale=f"[Discretion Auditor] Within discretion item {disc_item_id}.",
        discretion_item_id=disc_item_id,
    )
    await store.pg.close()
    return saved.id


async def _human_resolve(client: TestClient, iid: str, q: str, opts: list[str]) -> str:
    """Raise a decision via the store and resolve it via the HTTP endpoint (human path)."""
    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    store = SpecStore(pg, redis)
    d = Decision(question=q, options=opts)
    saved = await store.raise_decision(d, iid)
    await pg.close()
    r = client.post(
        f"/decisions/{saved.id}/resolve",
        json={"chosen": opts[0], "rationale": "because", "decided_by": "edo"},
    )
    assert r.status_code == 200, r.text
    return saved.id


async def _count_human_resolved(iid: str) -> int:
    store = await _make_store()
    try:
        return await store.count_human_resolved_decisions(iid)
    finally:
        await store.pg.close()


async def _list_resolved(iid: str) -> list[Decision]:
    store = await _make_store()
    try:
        return await store.list_decisions(iid, status="resolved")
    finally:
        await store.pg.close()


# ---------------------------------------------------------------------------
# a1: agent_resolve_decision saves as resolved, no escalation stream entry
# ---------------------------------------------------------------------------

def test_agent_resolve_saves_resolved_no_escalation(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    did = _run(_agent_resolve(iid, "which colour?", ["red", "blue"], "item_test123"))

    # decision is in the DB as resolved
    open_feed = client.get(f"/initiatives/{iid}/decisions").json()
    assert not any(d["id"] == did for d in open_feed), "agent-resolved must not appear on open feed"

    decisions = _run(_list_resolved(iid))
    match = next((d for d in decisions if d.id == did), None)
    assert match is not None, "agent-resolved decision must appear in resolved list"
    assert match.status == "resolved"
    assert match.resolver_type == "agent"
    assert "Discretion Auditor" in (match.rationale or "")


# ---------------------------------------------------------------------------
# a2: count_human_resolved_decisions excludes agent-resolved
# ---------------------------------------------------------------------------

def test_count_human_resolved_excludes_agent_resolved(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()

    # 4 human-resolved
    for i in range(4):
        _run(_human_resolve(client, iid, f"human q{i}", ["yes", "no"]))
    # 3 agent-resolved
    for i in range(3):
        _run(_agent_resolve(iid, f"agent q{i}", ["a", "b"], "item_disc"))

    count = _run(_count_human_resolved(iid))
    assert count == 4, f"expected 4 human-resolved, got {count}"


# ---------------------------------------------------------------------------
# a3: agent-resolved decisions appear in the decision log (list_decisions resolved)
# ---------------------------------------------------------------------------

def test_agent_resolved_visible_in_decision_log(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    agent_id = _run(_agent_resolve(iid, "internal detail?", ["a", "b"], "item_xyz"))
    human_id = _run(_human_resolve(client, iid, "product call?", ["yes", "no"]))

    resolved = _run(_list_resolved(iid))
    ids = [d.id for d in resolved]
    assert agent_id in ids, "agent-resolved decision must appear in decision log"
    assert human_id in ids, "human-resolved decision must appear in decision log"

    # resolver_type distinguishes them
    by_id = {d.id: d for d in resolved}
    assert by_id[agent_id].resolver_type == "agent"
    assert by_id[human_id].resolver_type == "human"


# ---------------------------------------------------------------------------
# a4: learn submit_learn gates memory — rationale_claims only written on confirm
# ---------------------------------------------------------------------------

def test_submit_learn_writes_rationale_claims_on_confirm(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()

    # Submit with rationale_claims
    claims = [
        {"claim": "Fast path reduced latency", "source_id": "dec_fake123", "source_type": "decision"}
    ]
    r = client.post(
        f"/initiatives/{iid}/learn",
        json={"summary": "It worked.", "rationale_claims": claims},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    memories = body["memory"]
    assert len(memories) == 1
    outcome = memories[0].get("outcome") or {}
    assert "rationale_claims" in outcome, "rationale_claims must be stored in memory.outcome"
    stored = outcome["rationale_claims"]
    assert len(stored) == 1
    assert stored[0]["claim"] == "Fast path reduced latency"


def test_submit_learn_without_rationale_claims_stores_no_claims(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    r = client.post(
        f"/initiatives/{iid}/learn",
        json={"summary": "All good."},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    outcome = (body["memory"][0].get("outcome") or {}) if body["memory"] else {}
    assert outcome.get("rationale_claims") is None or outcome.get("rationale_claims") == []


# ---------------------------------------------------------------------------
# a5: steering-ratio threshold — count at threshold triggers STEERING_RATIO_NOTE
# ---------------------------------------------------------------------------

def test_build_system_prompt_includes_steering_note_at_threshold():
    prompt_below = build_system_prompt("building", steering_count=STEERING_RATIO_THRESHOLD - 1)
    prompt_at = build_system_prompt("building", steering_count=STEERING_RATIO_THRESHOLD)
    prompt_above = build_system_prompt("building", steering_count=STEERING_RATIO_THRESHOLD + 2)

    assert "STEERING-RATIO OBSERVATION" not in prompt_below
    assert "STEERING-RATIO OBSERVATION" in prompt_at
    assert "STEERING-RATIO OBSERVATION" in prompt_above
    # note includes the count
    assert str(STEERING_RATIO_THRESHOLD) in prompt_at


def test_build_system_prompt_no_steering_note_when_zero():
    prompt = build_system_prompt("draft", steering_count=0)
    assert "STEERING-RATIO OBSERVATION" not in prompt


# ---------------------------------------------------------------------------
# a6: count_human_resolved_decisions: agent-resolved don't count toward threshold
# ---------------------------------------------------------------------------

def test_steering_ratio_threshold_ignores_agent_resolved(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()

    # 4 human + 3 agent = total 7, but only 4 should count
    for i in range(4):
        _run(_human_resolve(client, iid, f"hq{i}", ["yes", "no"]))
    for i in range(3):
        _run(_agent_resolve(iid, f"aq{i}", ["a", "b"], "item_disc2"))

    count = _run(_count_human_resolved(iid))
    assert count < STEERING_RATIO_THRESHOLD, (
        f"count={count} should be below threshold={STEERING_RATIO_THRESHOLD} "
        "since agent-resolved decisions are excluded"
    )
    assert count == 4


# ---------------------------------------------------------------------------
# a7: discretion_auditor rejects hallucinated item id
# ---------------------------------------------------------------------------

def test_audit_decision_rejects_hallucinated_item_id():
    """When the LLM returns an item id that doesn't exist in the spec, the auditor
    must treat it as within_discretion=False — no silent approval of fabricated grants."""
    real_items = [
        SpecItem(id="item_real001", text="The prompt structure.", status="confirmed"),
    ]

    # Mock the LLM to return a hallucinated item id.
    mock_llm = AsyncMock()
    mock_llm.complete_structured = AsyncMock(return_value={
        "within_discretion": True,
        "discretion_item_id": "item_HALLUCINATED",
        "reasoning": "Looks related.",
        "suggestion": "Go ahead.",
    })

    result = _run(audit_decision(
        question="What font size should I use?",
        options=["12pt", "14pt"],
        recommendation=None,
        discretion_items=real_items,
        llm=mock_llm,
    ))

    assert result.within_discretion is False, (
        "Hallucinated item id must cause within_discretion=False"
    )
    assert result.discretion_item_id is None


# ---------------------------------------------------------------------------
# a8: audit_decision with no confirmed discretion items — safe fallback, no LLM call
# ---------------------------------------------------------------------------

def test_audit_decision_no_discretion_items_no_llm():
    """With no confirmed discretion items, the auditor returns False immediately
    without calling the LLM (nothing to match against)."""
    mock_llm = AsyncMock()
    mock_llm.complete_structured = AsyncMock()

    result = _run(audit_decision(
        question="Should I use async or sync?",
        options=["async", "sync"],
        recommendation="async",
        discretion_items=[],
        llm=mock_llm,
    ))

    assert result.within_discretion is False
    mock_llm.complete_structured.assert_not_called()


# ---------------------------------------------------------------------------
# a9: resolve_decision (human path) sets resolver_type="human"
# ---------------------------------------------------------------------------

def test_resolve_decision_sets_human_resolver_type(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    _run(_human_resolve(client, iid, "do it?", ["yes", "no"]))

    resolved = _run(_list_resolved(iid))
    assert len(resolved) == 1
    assert resolved[0].resolver_type == "human"
