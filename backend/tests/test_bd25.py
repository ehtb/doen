"""BD-25: Auto-Approve Learnings and Compact Their Presentation.

Tests covering the service layer offline (no live LLM, no real DB for unit tests):
a1 — evaluate_learnings: high-confidence match → auto_approved=True.
a2 — evaluate_learnings: LLM error → all needs_review (safe fallback).
a3 — evaluate_learnings: hallucinated matched_item_id is rejected (auto_approved=False).
a4 — evaluate_learnings: no confirmed spec items → all needs_review without LLM call.
a5 — submit_learn: structured learnings write correct learning_approvals to memory.outcome.
a6 — submit_learn: bullet-point string is stored in memory.learnings.
a7 — submit_learn: legacy learnings= string still works (backward compat).
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.models import SpecItem
from app.services.learn import evaluate_learnings
from app.providers.llm import LLMError


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_disc_item(id: str, text: str) -> SpecItem:
    return SpecItem(id=id, text=text, status="confirmed")


def _make_mock_llm(within: bool, item_id: str | None, reasoning: str = "test") -> AsyncMock:
    mock = AsyncMock()
    mock.complete_structured = AsyncMock(return_value={
        "evaluations": [
            {
                "index": 0,
                "auto_approved": within,
                "matched_item_id": item_id,
                "reasoning": reasoning,
            }
        ]
    })
    return mock


# ---------------------------------------------------------------------------
# a1: high-confidence match → auto_approved=True
# ---------------------------------------------------------------------------

def test_evaluate_learnings_high_confidence_auto_approved():
    items = [_make_disc_item("item_disc001", "The exact confidence threshold value.")]
    mock = _make_mock_llm(True, "item_disc001", "Direct factual match.")
    result = _run(evaluate_learnings(["Using 0.8 as threshold was fine."], items, [], llm=mock))
    assert len(result) == 1
    assert result[0].auto_approved is True
    assert result[0].matched_item_id == "item_disc001"


# ---------------------------------------------------------------------------
# a2: LLM error → all needs_review (safe fallback)
# ---------------------------------------------------------------------------

def test_evaluate_learnings_llm_error_safe_fallback():
    items = [_make_disc_item("item_disc001", "something")]
    mock = AsyncMock()
    mock.complete_structured = AsyncMock(side_effect=LLMError("boom"))
    result = _run(evaluate_learnings(["A learning."], items, [], llm=mock))
    assert len(result) == 1
    assert result[0].auto_approved is False
    assert "fallback" in result[0].reasoning.lower()


# ---------------------------------------------------------------------------
# a3: hallucinated matched_item_id is rejected
# ---------------------------------------------------------------------------

def test_evaluate_learnings_rejects_hallucinated_item_id():
    items = [_make_disc_item("item_real001", "real item")]
    mock = _make_mock_llm(True, "item_HALLUCINATED", "Looks related.")
    result = _run(evaluate_learnings(["Some learning."], items, [], llm=mock))
    assert result[0].auto_approved is False
    assert result[0].matched_item_id is None


# ---------------------------------------------------------------------------
# a4: no confirmed spec items → all needs_review without LLM call
# ---------------------------------------------------------------------------

def test_evaluate_learnings_no_spec_items_no_llm_call():
    mock = AsyncMock()
    mock.complete_structured = AsyncMock()
    result = _run(evaluate_learnings(["A learning."], [], [], llm=mock))
    assert result[0].auto_approved is False
    mock.complete_structured.assert_not_called()


# ---------------------------------------------------------------------------
# a5: submit_learn writes learning_approvals to memory.outcome
# ---------------------------------------------------------------------------

def test_submit_learn_writes_learning_approvals(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    r = client.post(
        f"/initiatives/{iid}/learn",
        json={
            "summary": "Done.",
            "auto_approved_learnings": ["Always validate early."],
            "human_approved_learnings": ["Test at the boundary."],
        },
    )
    assert r.status_code == 201, r.text
    memories = r.json()["memory"]
    assert len(memories) == 1
    outcome = memories[0].get("outcome") or {}
    approvals = outcome.get("learning_approvals", [])
    assert len(approvals) == 2
    by_text = {a["text"]: a["approved_by"] for a in approvals}
    assert by_text["Always validate early."] == "auto"
    assert by_text["Test at the boundary."] == "human"


# ---------------------------------------------------------------------------
# a6: submit_learn formats learnings as bullet points in memory.learnings
# ---------------------------------------------------------------------------

def test_submit_learn_formats_learnings_as_bullets(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    r = client.post(
        f"/initiatives/{iid}/learn",
        json={
            "summary": "Done.",
            "auto_approved_learnings": ["First lesson."],
            "human_approved_learnings": ["Second lesson."],
        },
    )
    assert r.status_code == 201, r.text
    learnings = r.json()["memory"][0].get("learnings") or ""
    lines = [l for l in learnings.strip().split("\n") if l.strip()]
    assert all(l.startswith("- ") for l in lines), f"Expected bullet lines, got: {lines}"


# ---------------------------------------------------------------------------
# a7: legacy learnings= string still works
# ---------------------------------------------------------------------------

def test_submit_learn_legacy_learnings_string_compat(
    client: TestClient, make_initiative: Callable[[], str]
):
    iid = make_initiative()
    r = client.post(
        f"/initiatives/{iid}/learn",
        json={"summary": "Works.", "learnings": "Old style string learnings."},
    )
    assert r.status_code == 201, r.text
    mem = r.json()["memory"][0]
    assert mem.get("learnings") == "Old style string learnings."
