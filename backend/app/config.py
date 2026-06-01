"""Runtime configuration — read from the environment, with local-dev defaults
that match docker-compose.yml so `uvicorn app.main:app` works with no setup."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env if present. override=False so a real env var (e.g. an explicit
# DATABASE_URL export) always wins over the file — the file only fills gaps.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://doen:doen@localhost:5432/doen")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# No auth in this slice (spec 0001) — every initiative is owned by a single dev user.
# Auth/orgs are a later spec; this is the seam they will replace.
DEV_ORG_ID = "org_dev"
DEV_USER_ID = "user_dev"

# Embeddings (spec 0005). The provider is pluggable (constraint 2): text in, vector
# out. The dogfooding default routes through OpenRouter; a self-hoster swaps the model
# or points OPENROUTER_BASE_URL elsewhere. EMBEDDING_DIM must match both the model's
# output and the migration's vector(N) column.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
