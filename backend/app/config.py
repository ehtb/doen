"""Runtime configuration — read from the environment, with local-dev defaults
that match docker-compose.yml so `uvicorn app.main:app` works with no setup."""

from __future__ import annotations

import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://doen:doen@localhost:5432/doen")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# No auth in this slice (spec 0001) — every initiative is owned by a single dev user.
# Auth/orgs are a later spec; this is the seam they will replace.
DEV_ORG_ID = "org_dev"
DEV_USER_ID = "user_dev"
