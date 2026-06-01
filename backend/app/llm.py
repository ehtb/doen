"""Pluggable LLM provider for AI-assisted spec shaping (spec 0006, constraint 1).

Contract: structured prompt in, structured data out. The provider is handed a system
prompt, a user message, and a JSON schema; it returns a dict guaranteed to match the
schema — via a single forced tool call, so the output is structured, not free-form
markdown to regex (constraint 4) — or raises LLMError (constraint 7: clean failure, the
caller leaves the spec untouched). The hosted tier uses the default; a self-hoster
implements StructuredLLM against another vendor.

Dogfooding default: Claude via OpenRouter, reusing OPENROUTER_API_KEY (the same key as
the embedding provider) — no extra secret, no extra SDK. Keys are env-only (constraint 2).
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, SHAPING_MODEL


@runtime_checkable
class StructuredLLM(Protocol):
    async def complete_structured(
        self, *, system: str, user: str, schema: dict[str, Any], schema_name: str = "result"
    ) -> dict[str, Any]: ...


class LLMError(RuntimeError):
    """A shaping LLM call failed — missing key, network/API error, or unparseable output.
    Raised cleanly so the caller never persists a partial spec (constraint 7)."""


class OpenRouterClaude:
    """Claude via OpenRouter's OpenAI-compatible /chat/completions. A single forced tool
    call guarantees the model answers in the requested JSON shape (constraint 4)."""

    def __init__(
        self,
        *,
        api_key: str = OPENROUTER_API_KEY,
        model: str = SHAPING_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,  # injectable for tests
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
                "OPENROUTER_API_KEY is not set — cannot call the shaping model. "
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
    return OpenRouterClaude()
