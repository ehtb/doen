"""u2 — the Doen Advisor core (spec 0009).

Covers a2 (responses grounded in the confirmed spec, the stage, and relevant memory),
a5 (the prompt adapts to the lifecycle stage; shape produces proposals), and D2 -> c
(the "shape this initiative:" rail command reuses the 0006 full-draft generation, surfaced
as proposal cards, with NO silent spec write — constraint 4).

The LLM is faked (a single forced-tool provider, branching on schema_name so the same fake
serves both the advisor_turn and the shape command's proposed_spec). The felt quality of
the Advisor is the a9 HEADLINE, judged live. Integration tests need docker-compose PG+Redis.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable

import asyncpg
from redis import asyncio as aioredis

from app.config import DATABASE_URL, REDIS_URL
from app.models import (
    AcceptanceCriterion,
    ContextHit,
    ConversationContext,
    Initiative,
    Message,
    Spec,
    SpecItem,
    Verify,
)
from app.providers.llm import LLMError
from app.services.advisor import advise, build_system_prompt, build_user_message
from app.store import SpecStore

DIM = 1536

ADVISOR_PAYLOAD = {
    "reply": "Two constraints worth locking, and a criterion to judge it by.",
    "proposals": [
        {"section": "constraints", "text": "Magic links are single-use and expire in 15 minutes."},
        {"section": "discretion", "text": "Email copy and token length."},
        {
            "section": "acceptance",
            "text": "A used or expired link is rejected.",
            "verify_kind": "test",
            "verify_detail": "Replay a consumed link; assert 4xx + a clear message.",
        },
    ],
}

SHAPING_PAYLOAD = {
    "intent": "Let users sign in without a password via a single-use email magic link.",
    "constraints": ["Links are single-use and expire within 15 minutes.", "No password is stored."],
    "discretion": ["Email template and copy."],
    "acceptance": [
        {
            "text": "A used or expired link is rejected. [HEADLINE]",
            "verify_kind": "test",
            "verify_detail": "Replay a consumed link; assert 4xx.",
        }
    ],
}


class FakeLLM:
    """One forced-tool provider for both Advisor calls: returns the proposed_spec payload for
    the shape command and the advisor_turn payload otherwise. Captures every call."""

    def __init__(
        self,
        advisor_payload: dict | None = None,
        shaping_payload: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.advisor_payload = advisor_payload or ADVISOR_PAYLOAD
        self.shaping_payload = shaping_payload or SHAPING_PAYLOAD
        self.error = error
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if self.error:
            raise self.error
        return self.shaping_payload if schema_name == "proposed_spec" else self.advisor_payload


class FakeEmbedder:
    dimension = DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


def _run(coro) -> object:
    return asyncio.run(coro)


def _store_run(
    fn: Callable[[SpecStore], Awaitable[object]], embedder: FakeEmbedder | None = None
) -> object:
    async def go() -> object:
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return await fn(SpecStore(pg, redis, embedder=embedder))
        finally:
            await pg.close()
            await redis.aclose()

    return asyncio.run(go())


# --- a5: the prompt is stage-aware (pure) -------------------------------------
def test_system_prompt_adapts_to_stage():
    shape = build_system_prompt("shape")
    verify = build_system_prompt("verify")
    learn = build_system_prompt("learn")
    assert "**shape** stage" in shape and "PROPOSE concrete spec items" in shape
    assert "**verify** stage" in verify and "verdict" in verify and "never approve work" in verify
    assert "**learn** stage" in learn and "outcome summary" in learn
    # the spec-contract discipline is present at every stage (constraint 3)
    for prompt in (shape, verify, learn):
        assert "No estimation" in prompt and "constraints" in prompt
    assert shape != verify != learn


# --- a2: the user message grounds in spec + memory + history (pure) -----------
def test_user_message_grounds_in_spec_memory_history():
    spec = Spec(
        initiative_id="x", title="Passwordless", version=2, stage="shape",
        intent="Sign in without a password.",
        constraints=[
            SpecItem(text="No password is ever stored.", provenance="human", status="confirmed"),
            SpecItem(text="Links expire in 15m.", provenance="ai_proposed", status="proposed"),
        ],
        acceptance=[
            AcceptanceCriterion(
                text="Expired link rejected.", verify=Verify(kind="test", detail="replay it"),
                provenance="human", status="confirmed",
            )
        ],
    )
    ctx = ConversationContext(
        initiative=Initiative(id="x", title="Passwordless", stage="shape"),
        spec=spec,
        messages=[
            Message(initiative_id="x", role="human", content="how should sign-in work?"),
            Message(initiative_id="x", role="advisor", content="magic links."),
        ],
        memory=[ContextHit(initiative_id="other", type="memory", text="magic links beat OTP here", score=0.91)],
    )
    um = build_user_message(ctx)
    assert "No password is ever stored." in um            # confirmed constraint (governs)
    assert "Links expire in 15m." in um                   # proposed item shown too (avoid dup proposals)
    assert "verify: test" in um                           # acceptance verify rendered
    assert "magic links beat OTP here" in um              # relevant memory
    assert "how should sign-in work?" in um               # conversation history


# --- a2/a5: a live turn feeds the grounded, stage-named context to the LLM ----
def test_advise_grounds_and_persists(make_initiative: Callable[[], str]):
    iid = make_initiative()
    other = make_initiative()
    distinctive = "single-use magic-link sign-in that expires after ten minutes"
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            await store.set_stage(iid, "shape")
            spec = await store.get_spec(iid)
            assert spec is not None
            spec.constraints.append(
                SpecItem(text="No password is ever stored.", provenance="human", status="confirmed")
            )
            await store.save_spec(spec)
            await store.create_memory(other, distinctive)  # cross-initiative prior
            await store._drain()
            turn = await advise(store, iid, distinctive, llm=fake)  # anchors memory on this turn
            msgs = await store.list_messages(iid)
            return turn, msgs

        return inner()

    turn, msgs = _store_run(go, embedder=FakeEmbedder())
    assert isinstance(turn.human, Message) and turn.human.role == "human"
    assert turn.advisor.role == "advisor" and turn.advisor.content == ADVISOR_PAYLOAD["reply"]
    assert [m.role for m in msgs] == ["human", "advisor"]  # the exchange persisted, in order

    call = fake.calls[0]
    assert call["schema_name"] == "advisor_turn"
    assert "**shape** stage" in call["system"]                 # a5 — current stage drives the mode
    assert "No password is ever stored." in call["user"]       # a2 — confirmed spec
    assert distinctive in call["user"]                         # a2 — relevant memory retrieved


# --- a5: shape proposals ride along on the advisor message as cards -----------
def test_advise_proposals_become_cards(make_initiative: Callable[[], str]):
    iid = make_initiative()
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            await store.set_stage(iid, "shape")
            return await advise(store, iid, "help me shape the constraints", llm=fake)

        return inner()

    turn = _store_run(go, embedder=FakeEmbedder())
    cards = turn.advisor.metadata["proposals"]
    assert [c["section"] for c in cards] == ["constraints", "discretion", "acceptance"]
    acc = next(c for c in cards if c["section"] == "acceptance")
    assert acc["verify_kind"] == "test" and acc["verify_detail"]  # acceptance card is confirmable


# --- D2 -> c: the "shape this initiative:" rail command, no silent write -------
def test_shape_command_drafts_cards_without_writing_spec(make_initiative: Callable[[], str]):
    iid = make_initiative()
    fake = FakeLLM()

    def go(store: SpecStore):
        async def inner():
            before = await store.get_spec(iid)
            assert before is not None
            turn = await advise(
                store, iid, "shape this initiative: passwordless sign-in via magic links", llm=fake
            )
            after = await store.get_spec(iid)
            return turn, before.version, after.version if after else None

        return inner()

    turn, before_v, after_v = _store_run(go, embedder=FakeEmbedder())
    # routed through the 0006 full-draft generation (the proposed_spec schema)
    assert any(c["schema_name"] == "proposed_spec" for c in fake.calls)
    cards = turn.advisor.metadata["proposals"]
    # the whole draft surfaced as cards: 2 constraints + 1 discretion + 1 acceptance
    assert sum(c["section"] == "constraints" for c in cards) == 2
    assert sum(c["section"] == "discretion" for c in cards) == 1
    assert sum(c["section"] == "acceptance" for c in cards) == 1
    assert "drafted a full spec" in turn.advisor.content
    # constraint 4 — nothing was written to the spec; the human confirms the cards
    assert after_v == before_v


# --- endpoint: a turn persists both messages; an LLM failure leaves no orphan --
def test_advisor_endpoint_persists_turn(client, make_initiative: Callable[[], str], monkeypatch):
    monkeypatch.setattr("app.services.advisor.get_advisor_llm", lambda: FakeLLM())
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())
    iid = make_initiative()
    r = client.post(f"/initiatives/{iid}/advisor", json={"content": "what should I build first?"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["human"]["role"] == "human" and body["advisor"]["role"] == "advisor"
    assert body["advisor"]["metadata"]["proposals"]  # cards came back

    got = client.get(f"/initiatives/{iid}/messages").json()
    assert [m["role"] for m in got] == ["human", "advisor"]


def test_advisor_endpoint_llm_failure_no_orphan(
    client, make_initiative: Callable[[], str], monkeypatch
):
    monkeypatch.setattr("app.services.advisor.get_advisor_llm", lambda: FakeLLM(error=LLMError("boom")))
    monkeypatch.setattr("app.store.get_embedding_provider", lambda: FakeEmbedder())
    iid = make_initiative()
    r = client.post(f"/initiatives/{iid}/advisor", json={"content": "hello"})
    assert r.status_code == 502, r.text
    # the human turn is only persisted on success, so a failed call leaves no orphan message
    assert client.get(f"/initiatives/{iid}/messages").json() == []
