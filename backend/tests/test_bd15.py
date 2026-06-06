"""BD-15: Research Initiatives (engineering/research framing)."""

from __future__ import annotations

import pytest
from typing import Any
from fastapi.testclient import TestClient
from app.services.shaping import SHAPING_SYSTEM_PROMPT_RESEARCH, SHAPING_SYSTEM_PROMPT
from app.models import ContextHit

class FakeLLM:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, user, schema, schema_name="result"):
        self.calls.append({"system": system, "user": user})
        return self.payload

def test_research_initiative_framing(client: TestClient, project: str, monkeypatch: Any):
    # a1: Creation uses research framing if specified.
    fake_llm = FakeLLM({
        "title": "Research A",
        "intent": "Investigate X",
        "constraints": [],
        "discretion": [],
        "acceptance": [{"id": "c1", "text": "Finding Y", "verify": {"kind": "human_judgment", "detail": "..."}}],
        "units": []
    })
    
    monkeypatch.setattr("app.services.shaping.get_shaping_llm", lambda: fake_llm)
    async def mock_get_context(*a, **kw):
        return []
    monkeypatch.setattr("app.store.SpecStore.get_context", mock_get_context)

    # 1. Shape research initiative
    res = client.post(f"/projects/{project}/initiatives/shape", json={
        "description": "Investigate X",
        "initiative_type": "research"
    })
    assert res.status_code == 201, res.text
    init = res.json()
    assert init["initiative_type"] == "research"
    
    # Check that the research prompt was used
    found_research_prompt = any(SHAPING_SYSTEM_PROMPT_RESEARCH in c["system"] for c in fake_llm.calls)
    assert found_research_prompt

    # 2. Verify spec also has the type
    spec_res = client.get(f"/specs/{init['id']}")
    assert spec_res.json()["initiative_type"] == "research"

def test_evidence_submission_via_router(client: TestClient, make_initiative: Any, monkeypatch: Any):
    # BD-15: Submit evidence from conversation rail (no MCP) triggers synthesis.
    iid = make_initiative()
    
    # Need a confirmed criterion to submit evidence against
    spec = client.get(f"/specs/{iid}").json()
    spec["acceptance"] = [{
        "id": "c1", "text": "C1", "status": "confirmed", 
        "verify": {"kind": "human_judgment", "detail": "..."}
    }]
    client.put(f"/specs/{iid}", json=spec)

    synthesis_called = False
    async def mock_synthesis(store, initiative_id, **kwargs):
        nonlocal synthesis_called
        synthesis_called = True
    
    monkeypatch.setattr("app.services.review.generate_verification_synthesis", mock_synthesis)

    # Submit evidence
    res = client.post(f"/specs/{iid}/criteria/c1/evidence", json={"evidence": "Found it!"})
    assert res.status_code == 200, res.text
    
    # Wait for the background task to complete (store._drain() is the intended mechanism)
    from app.store import SpecStore
    # SpecStore is instantiated per-request from shared pg/redis in app.state
    store = SpecStore(client.app.state.pg, client.app.state.redis)
    import asyncio
    asyncio.run(store._drain())
    
    assert synthesis_called
    
    updated_spec = res.json()
    # Find criterion c1 in the updated spec
    c1 = next(c for c in updated_spec["acceptance"] if c["id"] == "c1")
    assert c1["verification_status"] == "evidence_submitted"
    assert c1["evidence"] == "Found it!"
