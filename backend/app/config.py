"""Runtime configuration — read from the environment, with local-dev defaults
that match docker-compose.yml so `uvicorn app.main:app` works with no setup."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend/ if present. override=False so a real env var (e.g. an explicit
# DATABASE_URL export) always wins over the file — the file only fills gaps.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://doen:doen@localhost:5432/doen")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# No auth in this slice (spec 0001) — every initiative is owned by a single dev user.
# Auth/orgs are a later spec; this is the seam they will replace.
DEV_ORG_ID = "org_dev"
DEV_USER_ID = "user_dev"

# Embeddings (spec 0005). The provider is pluggable (constraint 2): text in, vector
# out. Any OpenAI-compatible endpoint works — point LLM_BASE_URL at it and set LLM_API_KEY.
# EMBEDDING_DIM must match both the model's output and the migration's vector(N) column.
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

# AI-assisted spec shaping (spec 0006). The LLM provider is pluggable; the dogfooding
# default routes Claude through OpenRouter, reusing LLM_API_KEY (no extra secret).
SHAPING_MODEL = os.getenv("SHAPING_MODEL", "anthropic/claude-sonnet-4.6")

# MCP transport (BD-10). "stdio" (default) keeps the dev behaviour unchanged — run
# `python -m app.mcp_server` as a subprocess. "http" mounts the MCP server on the FastAPI
# app at /mcp so remote Claude Code instances can connect without a local subprocess.
# WARNING: HTTP MCP is intended for VPC/private network deployment only.
# Do not expose to the public internet without authentication (see spec 0007).
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")

# MCP DNS-rebinding protection (HTTP transport only). Comma-separated list of Host header
# values to accept, e.g. "myapp.railway.app". Empty string (default) disables the check —
# safe when the deployment is already VPC/proxy-controlled (Railway, Fly, etc.).
MCP_ALLOWED_HOSTS = os.getenv("MCP_ALLOWED_HOSTS", "")
