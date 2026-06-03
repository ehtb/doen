"""Pluggable LLM provider for AI-assisted spec shaping (spec 0006, constraint 1).

Contract: structured prompt in, structured data out. The provider is handed a system
prompt, a user message, and a JSON schema; it returns a dict guaranteed to match the
schema — via a single forced tool call, so the output is structured, not free-form
markdown to regex (constraint 4) — or raises LLMError (constraint 7: clean failure, the
caller leaves the spec untouched). The hosted tier uses the default; a self-hoster
implements StructuredLLM against another vendor.

Dogfooding default: any OpenAI-compatible endpoint (LLM_BASE_URL) with LLM_API_KEY.
OpenRouter is the out-of-the-box provider; swap the env vars to use any other.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config import LLM_API_KEY, LLM_BASE_URL, SHAPING_MODEL


@runtime_checkable
class StructuredLLM(Protocol):
    async def complete_structured(
        self, *, system: str, user: str, schema: dict[str, Any], schema_name: str = "result"
    ) -> dict[str, Any]: ...


class LLMError(RuntimeError):
    """A shaping LLM call failed — missing key, network/API error, or unparseable output.
    Raised cleanly so the caller never persists a partial spec (constraint 7)."""


class OpenAICompatibleLLM:
    """Any OpenAI-compatible /chat/completions endpoint. A single forced tool call
    guarantees the model answers in the requested JSON shape (constraint 4)."""

    def __init__(
        self,
        *,
        api_key: str = LLM_API_KEY,
        model: str = SHAPING_MODEL,
        base_url: str = LLM_BASE_URL,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,  # injectable for tests
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport

    async def complete_structured(
        self, *, system: str, user: str, schema: dict[str, Any], schema_name: str = "result"
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError(
                "LLM_API_KEY is not set — cannot call the shaping model. "
                "Export it (or add it to backend/.env)."
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": [{
                "type": "function",
                "function": {
                    "name": schema_name,
                    "description": "Return the result strictly in this shape.",
                    "parameters": schema,
                },
            }],
            "tool_choice": {"type": "function", "function": {"name": schema_name}},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as e:
            raise LLMError(f"shaping request failed: {e}") from e
        if resp.status_code != 200:
            raise LLMError(f"shaping model returned {resp.status_code}: {resp.text[:300]}")
        try:
            call = resp.json()["choices"][0]["message"]["tool_calls"][0]
            return json.loads(call["function"]["arguments"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMError(f"shaping model returned no parseable tool call: {e}") from e


def get_shaping_llm() -> StructuredLLM:
    """The dogfooding default. Swap the body (or branch on an env var) to self-host."""
    return OpenAICompatibleLLM()


def get_advisor_llm() -> StructuredLLM:
    """The Doen Advisor (0009) reuses this same provider — same class, same env key, no
    second AI integration path (0009 constraint 2). Kept as its own factory so the Advisor
    has a clean monkeypatch seam in tests, mirroring get_shaping_llm."""
    return OpenAICompatibleLLM()


def get_review_llm() -> StructuredLLM:
    """The Advisor's self-review pass (BD-14): shaping classification and verification
    synthesis. Separate factory from get_shaping_llm so each can be patched independently
    in tests without affecting the other."""
    return OpenAICompatibleLLM()
