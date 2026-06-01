# Contributing to Doen

Thanks for your interest. Doen is spec-driven — features are shaped as specs *inside Doen
itself*, then built against them. This guide covers the practical setup; the philosophy lives
in [`CLAUDE.md`](CLAUDE.md) and [`docs/spec-contract.md`](docs/spec-contract.md).

## Development setup

Two ways to run it:

- **Docker (run)** — matches the alpha: `cp backend/.env.example backend/.env`, add your
  `LLM_API_KEY`, then `docker compose up` (production build). See the
  [getting-started guide](docs/getting-started.md).
- **Docker (develop)** — hot-reload with your source bind-mounted:
  `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`.
- **On your host:** `make infra` starts Postgres + Redis in Docker; `make dev` then runs the
  backend (`:8000`) and web (`:3000`) together with hot-reload.
  - Backend deps: `python -m venv backend/.venv && cd backend && .venv/bin/pip install -e ".[dev]"`
  - Web deps: `cd web && npm install`

## Tests

```bash
cd backend && .venv/bin/python -m pytest
```

Integration tests need Postgres + Redis up (`make infra`). External APIs (the LLM and embedding
providers) are faked in tests, so no API key is needed to run the suite.

## How we work

- Build only what the active spec covers; out-of-scope ideas become a note, not code.
- Small commits — one work unit per commit, referencing the unit.
- Don't guess on intent — surface a decision instead.
- No estimation anywhere (no story points, hours, or velocity).

## Code style

- **Backend:** async throughout, `asyncpg` (no ORM), Pydantic v2. Postgres is the source of
  truth; Redis is a derived cache that must always be rebuildable from it.
- **Web:** Next.js App Router, TypeScript, Tailwind v4, shadcn/ui. The design language (palette,
  type, trust cues) lives in `web/app/globals.css`.

## License

By contributing, you agree that your contributions are licensed under the Business Source
License 1.1 — see [`LICENSE`](LICENSE).
