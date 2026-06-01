"""Pluggable embedding providers (spec 0005, constraint 2).

The contract is deliberately tiny: text in, vector out. The hosted tier wires a
high-quality API provider; a self-hoster swaps in a local model or a different API
by implementing `EmbeddingProvider` and pointing `get_embedding_provider` at it.
The store depends on the Protocol, never on a concrete vendor.

Dogfooding default: OpenRouter (openai/text-embedding-3-small, 1536-dim).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from app.config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """text in, vector out. `dimension` must match the specs' vector(N) column."""

    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingError(RuntimeError):
    """A provider could not produce embeddings (missing key, API error, bad shape)."""


class OpenRouterEmbeddings:
    """Calls OpenRouter's OpenAI-compatible /embeddings endpoint. One short-lived
    httpx client per batch — embedding is infrequent and async/best-effort, so a
    pooled client isn't worth the lifecycle."""

    def __init__(
        self,
        *,
        api_key: str = OPENROUTER_API_KEY,
        model: str = EMBEDDING_MODEL,
        dimension: int = EMBEDDING_DIM,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise EmbeddingError(
                "OPENROUTER_API_KEY is not set — cannot generate embeddings. "
                "Export it (or add it to backend/.env) to enable the default provider."
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": texts},
            )
        if resp.status_code != 200:
            raise EmbeddingError(f"OpenRouter embeddings {resp.status_code}: {resp.text[:300]}")
        data = resp.json().get("data")
        if not data or len(data) != len(texts):
            raise EmbeddingError(f"OpenRouter returned {len(data or [])} vectors for {len(texts)} inputs")
        # the API returns results indexed; sort to be safe before stripping the index
        return [row["embedding"] for row in sorted(data, key=lambda r: r["index"])]


def get_embedding_provider() -> EmbeddingProvider:
    """The dogfooding default. Swap the body (or branch on an env var) to self-host."""
    return OpenRouterEmbeddings()
