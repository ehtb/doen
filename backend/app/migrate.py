"""Minimal forward-only migration runner.

Applies every `migrations/*.sql` file in filename order, once, recording applied
names in a `_migrations` ledger so re-runs are no-ops. Run it directly:

    python -m app.migrate
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

from app.config import DATABASE_URL

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def run_migrations(conn: asyncpg.Connection) -> list[str]:
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS _migrations (
               name       TEXT PRIMARY KEY,
               applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
           )"""
    )
    applied = {r["name"] for r in await conn.fetch("SELECT name FROM _migrations")}

    just_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        async with conn.transaction():
            await conn.execute(path.read_text())
            await conn.execute("INSERT INTO _migrations (name) VALUES ($1)", path.name)
        just_applied.append(path.name)
    return just_applied


async def _main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        applied = await run_migrations(conn)
    finally:
        await conn.close()
    print("applied:", ", ".join(applied) if applied else "(nothing new)")


if __name__ == "__main__":
    asyncio.run(_main())
