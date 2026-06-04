# Doen

**The intent layer above agentic coding.** You author a living spec; agents build against it
and surface decisions back to you. Doen is where you decide *what's worth building* and verify
it was built *right* — not where code gets typed by hand.

## The problem

Coding agents can write the code. What they can't do is decide what's worth building, hold the
line on the constraints that matter, or prove to you that what they shipped is what you meant.
Today that intent lives in scattered prompts, PR descriptions, and your head — and it
evaporates the moment the task is done. Every feature starts from a blank page; nothing the
team learns compounds.

## What Doen is

Doen is a living spec that governs an agent or an investigation. You choose a framing:
- **Engineering** initiatives drive an executor (Claude Code, over MCP) to build code against
  your constraints.
- **Research** initiatives guide a collaborative investigation with the Advisor to reach a
  well-reasoned conclusion or finding.

In both, you shape the spec — its intent, the constraints that must not be crossed, the latitude
available, and how the work will be judged. You verify the result against your criteria — not
by reading diffs or raw notes. When it's done, the decisions and outcomes become memory the
next initiative can draw on — with continuous drift detection to keep that memory in sync with
the evolving codebase.

## The loop

**shape → investigate/implement → verify → learn**

- **shape** — describe a feature or question; the AI drafts a full spec, informed by past
  initiatives, that you correct and confirm.
- **investigate/implement** — for engineering, an executor claims units over MCP and builds;
  for research, you work with the Advisor to gather findings and resolve the question.
- **verify** — you judge findings or code against the criteria; only you issue a verdict.
- **learn** — capture the outcome; it's embedded into memory and retrieved to inform what comes
  next. Drift detection (BD-12) ensures this memory stays accurate even as the codebase
  changes.

The loop compounds: every initiative completed makes the next one better-informed.

## Get started

Clone, add one API key, run one command — you'll have a running instance and a spec shaped by
AI in under ten minutes.

→ **[Getting started](docs/getting-started.md)**

## How it works

- **Backend** — FastAPI (async). Postgres is the source of truth: the spec is one JSONB
  document per initiative; decisions, work units, and memory are rows. Redis is the derived hot
  cache and real-time coordination. pgvector powers memory retrieval.
- **Executor seam** — an MCP server exposes the spec, decisions, work units, and memory tools so
  an agent can read the intent and act on it.
- **Web** — Next.js: the dashboard, the living-spec view, and the steering rail where decisions
  land for your judgment.

Single-user and local for now. Multi-user is a later step.

## Running it

Two ways to bring up the full stack:

```bash
# Run Doen (production build — what the getting-started guide uses)
docker compose up

# Develop Doen (hot-reload: backend on uvicorn --reload, web on next dev,
# your source bind-mounted so edits reflect live — no rebuild)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Plain `docker compose up` builds images and serves a production build — fast to run, but code
changes need a rebuild (`docker compose up --build`). The dev overlay swaps in the reloaders and
mounts your source, so saves are picked up live. (Prefer running on your host instead?
`make dev` does the same hot-reload without containers.)

## License

Business Source License 1.1 — see [LICENSE](LICENSE).
