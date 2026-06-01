"""Spec 0006 u2/u3 — AI-assisted shaping (a2, a3, a4, a5, a6).

shape_spec is exercised against a FakeStore + FakeLLM (no DB, no network). The endpoint
is exercised through the TestClient with the LLM and embedder faked via monkeypatch, so
the whole path stays offline. The a8 HEADLINE (the felt quality of the draft) is judged
live in u4.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Callable

import asyncpg

from app.config import DATABASE_URL
from app.models import AcceptanceCriterion, ContextHit, SpecItem
from app.providers.llm import LLMError
from app.services.shaping import create_from_description, shape_spec

PAYLOAD = {
    "title": "Passwordless sign-in",
    "intent": "Let users sign in without a password using a single-use email magic link.",
    "constraints": [
        "Links are single-use and expire within 15 minutes.",
        "No password is ever stored.",
    ],
    "discretion": ["Email template and copy.", "Token length within reason."],
    "acceptance": [
        {
            "text": "A used or expired link is rejected with a clear error.",
            "verify_kind": "test",
            "verify_detail": "Replay a consumed link; assert 4xx + a clear message.",
        },
        {
            "text": "A human signs in end to end via the emailed link. [HEADLINE]",
            "verify_kind": "human_judgment",
            "verify_detail": "Walk the full flow in the UI.",
        },
    ],
    "units": [
        {
            "title": "Token issuance + email",
            "scope": "Generate single-use tokens and email the magic link.",
            "criteria": [1],
        },
        {
            "title": "Link verification + expiry",
            "scope": "Verify, consume, and expire links.",
            "criteria": [0],
        },
    ],
}


def _run(coro) -> object:
    return asyncio.run(coro)


class FakeLLM:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error:
            raise self.error
        return self.payload


class FakeStore:
    """Stands in for SpecStore — shape_spec only needs get_context."""

    def __init__(self, hits: list[ContextHit]) -> None:
        self._hits = hits
        self.last_query: str | None = None
        self.last_project: str | None = None

    async def get_context(
        self, query: str, limit: int = 8, *, project_id: str | None = None
    ) -> list[ContextHit]:
        self.last_query = query
        self.last_project = project_id
        return self._hits


class FakeEmbedder:
    dimension = 1536

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "big")
            rng = random.Random(seed)
            out.append([rng.uniform(-1.0, 1.0) for _ in range(self.dimension)])
        return out


# --- shape_spec unit tests (no DB / no network) ------------------------------------
def test_shape_spec_produces_valid_proposed_items():
    # a2 — structured items are produced; a5 — valid models with verify populated;
    # a3 (model level) — everything is ai_proposed / proposed; 0011 C2 — a title + units too.
    res = _run(shape_spec(FakeStore([]), "passwordless sign-in", llm=FakeLLM(PAYLOAD)))
    assert res.title == "Passwordless sign-in"
    assert res.intent
    assert res.constraints and all(isinstance(i, SpecItem) for i in res.constraints)
    assert res.discretion and all(isinstance(i, SpecItem) for i in res.discretion)
    assert res.acceptance and all(
        isinstance(a, AcceptanceCriterion) and a.verify.kind and a.verify.detail
        for a in res.acceptance
    )
    everything = res.constraints + res.discretion + res.acceptance
    assert all(i.provenance == "ai_proposed" and i.status == "proposed" for i in everything)
    # 0011 C2 — proposed units, each carrying the acceptance indexes it satisfies
    assert [u.title for u in res.units] == ["Token issuance + email", "Link verification + expiry"]
    assert res.units[0].criterion_indexes == [1] and res.units[1].criterion_indexes == [0]


def test_shape_spec_feeds_context_before_llm():
    # a4 — get_context is called with the description, and its hits feed the prompt.
    hit = ContextHit(
        initiative_id="build-doen-0002-spec-editing", type="decision",
        text="Editing a confirmed item reverts it to proposed", score=0.9,
    )
    store = FakeStore([hit])
    llm = FakeLLM(PAYLOAD)
    res = _run(shape_spec(store, "rules for editing spec items", llm=llm))
    assert store.last_query == "rules for editing spec items"
    assert "reverts it to proposed" in llm.calls[0]["user"]
    assert res.context_used == [hit]


def test_shape_spec_no_context_still_succeeds():
    # a4 — graceful degradation: empty corpus, shaping still produces a spec.
    llm = FakeLLM(PAYLOAD)
    res = _run(shape_spec(FakeStore([]), "anything", llm=llm))
    assert res.context_used == []
    assert res.constraints and res.acceptance


def test_shape_spec_malformed_output_raises():
    # a6 (service level) — output missing required fields -> LLMError, nothing returned.
    bad = FakeLLM({"intent": "x", "constraints": ["c"]})  # no discretion / acceptance keys
    try:
        _run(shape_spec(FakeStore([]), "desc", llm=bad))
        raise AssertionError("expected LLMError")
    except LLMError:
        pass


# --- endpoint tests (TestClient; LLM + embedder faked) -----------------------------
def test_shape_endpoint_persists_proposed(client, make_initiative: Callable[[], str], monkeypatch):
    # a3 — every generated item persists as ai_proposed / proposed; a7-precondition: they're
    # ordinary proposed items, immediately actionable via the existing editing flow.
    monkeypatch.setattr("app.services.shaping.get_shaping_llm", lambda: FakeLLM(PAYLOAD))
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())
    iid = make_initiative()
    r = client.post(f"/specs/{iid}/shape", json={"description": "passwordless sign-in via email links"})
    assert r.status_code == 201, r.text
    spec = r.json()
    items = spec["constraints"] + spec["discretion"] + spec["acceptance"]
    assert items, "no items persisted"
    assert all(i["provenance"] == "ai_proposed" and i["status"] == "proposed" for i in items)
    assert all(a["verify"]["kind"] and a["verify"]["detail"] for a in spec["acceptance"])
    assert spec["intent"]  # set on the blank spec


def test_shape_endpoint_llm_failure_leaves_spec_untouched(
    client, make_initiative: Callable[[], str], monkeypatch
):
    # a6 — a failed LLM call surfaces an error and the spec is unchanged.
    monkeypatch.setattr("app.services.shaping.get_shaping_llm", lambda: FakeLLM(error=LLMError("boom")))
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())
    iid = make_initiative()
    before = client.get(f"/specs/{iid}").json()
    r = client.post(f"/specs/{iid}/shape", json={"description": "x"})
    assert r.status_code == 502, r.text
    after = client.get(f"/specs/{iid}").json()
    assert after["version"] == before["version"]
    assert after["intent"] == before["intent"]
    assert len(after["constraints"]) == len(before["constraints"])


def _drop(iid: str) -> None:
    async def go() -> None:
        c = await asyncpg.connect(DATABASE_URL)
        try:
            await c.execute("DELETE FROM initiatives WHERE id = $1", iid)  # cascade: spec + units
        finally:
            await c.close()

    asyncio.run(go())


# --- 0011 a3: description-first creation IS shaping (TestClient; LLM + embedder faked) -----
def test_create_from_description_endpoint(client, monkeypatch):
    monkeypatch.setattr("app.services.shaping.get_shaping_llm", lambda: FakeLLM(PAYLOAD))
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())

    r = client.post(
        "/projects/build-doen/initiatives/shape",
        json={"description": "passwordless sign-in via single-use email links"},
    )
    assert r.status_code == 201, r.text
    init = r.json()
    try:
        # the Advisor named the initiative (title from shaping) and it's born Draft, in the project
        assert init["id"].endswith("-passwordless-sign-in")
        assert init["state"] == "draft" and init["project_id"] == "build-doen"

        # the whole spec is drafted as proposals to confirm item by item (a3)
        spec = client.get(f"/specs/{init['id']}").json()
        assert spec["intent"]
        items = spec["constraints"] + spec["discretion"] + spec["acceptance"]
        assert len(spec["constraints"]) == 2 and len(spec["acceptance"]) == 2
        assert all(i["provenance"] == "ai_proposed" and i["status"] == "proposed" for i in items)

        # proposed units came with it, mapped to the persisted acceptance criteria
        units = client.get(f"/specs/{init['id']}/units").json()
        assert len(units) == 2 and all(u["status"] == "proposed" for u in units)
        acc_ids = {a["id"] for a in spec["acceptance"]}
        assert all(cid in acc_ids for u in units for cid in u["criterion_ids"])

        # an empty description is rejected; an unknown project -> 404
        assert client.post(
            "/projects/build-doen/initiatives/shape", json={"description": "  "}
        ).status_code == 422
        assert client.post(
            "/projects/ghost/initiatives/shape", json={"description": "x"}
        ).status_code == 404
    finally:
        _drop(init["id"])
