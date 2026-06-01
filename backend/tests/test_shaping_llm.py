"""Spec 0006 u1 — the pluggable shaping LLM provider (a6 error path + happy path).

Hermetic: httpx.MockTransport stands in for OpenRouter, so no key and no network are
needed. The forced-tool-call contract (constraint 4) and clean failure (constraint 7)
are what's under test here.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.llm import LLMError, OpenRouterClaude

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _run(coro) -> object:
    return asyncio.run(coro)


def _provider(handler, key: str = "sk-test") -> OpenRouterClaude:
    return OpenRouterClaude(api_key=key, transport=httpx.MockTransport(handler))


def _tool_response(args: dict) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"tool_calls": [
            {"function": {"name": "result", "arguments": json.dumps(args)}}
        ]}}]
    })


def test_happy_path_returns_parsed_dict():
    def handler(_req: httpx.Request) -> httpx.Response:
        return _tool_response({"answer": "ok"})

    out = _run(_provider(handler).complete_structured(system="s", user="u", schema=SCHEMA))
    assert out == {"answer": "ok"}


def test_missing_key_raises():
    with pytest.raises(LLMError):
        _run(OpenRouterClaude(api_key="").complete_structured(system="s", user="u", schema=SCHEMA))


def test_http_error_raises():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    with pytest.raises(LLMError):
        _run(_provider(handler).complete_structured(system="s", user="u", schema=SCHEMA))


def test_malformed_response_raises():
    # 200 OK but no tool_calls — the model didn't honor the forced tool.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "no tool call"}}]})

    with pytest.raises(LLMError):
        _run(_provider(handler).complete_structured(system="s", user="u", schema=SCHEMA))
