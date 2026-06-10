"""Evals for the type-inference prompt (BD-28).

Live LLM tests — require LLM_API_KEY. Each fixture is a (prompt, expected_type) pair;
the model must classify correctly across a representative spread of engineering and
research phrasings to confirm the prompt in app/prompts/type-inference.txt is working.

Run with: pytest tests/evals/ -v
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import LLM_API_KEY
from app.providers.llm import OpenAICompatibleLLM
from app.services.shaping import infer_initiative_type

pytestmark = pytest.mark.skipif(not LLM_API_KEY, reason="LLM_API_KEY not set")

FIXTURES: list[tuple[str, str]] = [
    # engineering — building / changing / fixing software
    ("build a user authentication system with JWT tokens", "engineering"),
    ("add dark mode support to the web app", "engineering"),
    ("implement rate limiting on the API gateway", "engineering"),
    ("add pagination to the project list endpoint", "engineering"),
    # research — investigating / evaluating / comparing options
    ("research competing approaches to distributed caching in Python", "research"),
    ("evaluate three LLM providers for cost and quality tradeoffs", "research"),
    ("investigate whether to use Postgres JSONB or separate tables for spec items", "research"),
    ("compare authentication libraries for our FastAPI backend before choosing one", "research"),
]


@pytest.mark.parametrize("prompt,expected", FIXTURES, ids=[p[:40] for p, _ in FIXTURES])
def test_type_inference_prompt(prompt: str, expected: str) -> None:
    # Fresh client per test — the singleton httpx client is bound to the first event loop
    # created by asyncio.run(); subsequent calls on a new loop fail with "event loop closed".
    result = asyncio.run(infer_initiative_type(prompt, llm=OpenAICompatibleLLM()))
    assert result == expected, (
        f"Prompt {prompt!r}: expected {expected!r}, got {result!r}. "
        f"Check app/prompts/type-inference.txt if this regresses."
    )
