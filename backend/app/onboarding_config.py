"""BD-9: server-side onboarding document manifest.

Lists every file that setup_project installs into a user's working directory.
Updating this module changes what gets installed on the next run — no frontend
deploy needed (constraint item_a2118c0715c8).

Each entry is an OnboardingDocument with:
  path    — relative path within the target project directory
  content — verbatim file content to write

The MCP tool (setup_project) reads DOCUMENTS and writes each file. The API
endpoint (/projects/{id}/onboarding) returns the prompt the dashboard hint
surfaces so users know how to trigger setup from their executor.
"""

from __future__ import annotations

from dataclasses import dataclass

_CLAUDE_MD = """\
# Doen — Spec-Driven Development

This project uses [Doen](https://github.com/ehtb/doen) as its intent layer.
Every initiative is a living spec that constrains what you build and verifies
what was built. Ground yourself in the spec before touching any code.

## Before you build anything

1. Call `get_spec("<initiative-id>")` to read the full living spec.
2. Call `get_conversation_summary("<initiative-id>")` to understand the WHY.
3. Act within constraints, decide within discretion, escalate everything else.

## Operating loop

1. `get_spec(initiative_id)` — read intent, constraints, discretion, acceptance criteria.
2. `get_conversation_summary(initiative_id)` — understand the decisions behind the spec.
3. Build against confirmed items only. Out-of-scope ideas → `raise_decision`.
4. When you hit a call outside constraints + discretion, `raise_decision` and STOP.
5. After completing work: `submit_evidence(initiative_id, criteria_results)` per criterion.

## MCP tools

| Tool | When to use |
|------|-------------|
| `get_spec(initiative_id)` | Always first — ground yourself in the spec |
| `get_conversation_summary(initiative_id)` | Understand why constraints exist |
| `raise_decision(initiative_id, question, options)` | Escalate intent questions |
| `wait_for_decision(decision_id)` | Block until a decision resolves |
| `submit_evidence(initiative_id, criteria_results)` | Mark criteria as verified |
| `get_criteria_status(initiative_id)` | Check verification progress |
| `get_context(initiative_id, query)` | Retrieve relevant prior patterns |
| `setup_project(project_path)` | Re-run onboarding (installs/updates these docs) |

## Rules

- **You never self-approve work.** Submit evidence; the human issues the verdict.
- **No story points, hours, or velocity.** Ever.
- **State is inferred, not set.** Initiative lifecycle advances from criterion status.
- **Postgres is the only source of truth.** Don't store durable state anywhere else.
"""

_DOEN_SETUP_MD = """\
# Doen MCP Server — Setup Guide

This guide covers connecting your executor (Claude Code, Cursor, Windsurf, etc.)
to the Doen MCP server so it can read and write specs.

## Prerequisites

- A running Doen instance (backend + Postgres + Redis). See `docker-compose.yml`.
- Python 3.11+ with Doen's backend dependencies installed (`pip install -e .` in
  `backend/`).

## Claude Code (stdio mode)

Add the following to your Claude Code MCP configuration. You can do this in
`~/.claude/settings.json` (global) or `.claude/settings.json` (project-local):

```json
{
  "mcpServers": {
    "doen": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/doen/backend",
      "env": {
        "DATABASE_URL": "postgresql://doen:doen@localhost:5432/doen",
        "REDIS_URL": "redis://localhost:6379"
      }
    }
  }
}
```

Replace `/path/to/doen/backend` with the actual path to the Doen `backend/`
directory, and update `DATABASE_URL` / `REDIS_URL` to match your environment.

## Verify the connection

Once configured, start a new Claude Code session and run:

    Call get_spec on any initiative ID you know (e.g. "BD-1").

A JSON response with the spec confirms the connection is working. If you get
an error, check that the backend is running and the env vars are correct.

## Re-running onboarding

To install updated setup docs at any time, paste this prompt into your executor:

    Set up Doen in this project directory.
    Call setup_project(project_path="<absolute path to your project>") via the
    Doen MCP server. This installs or updates the Doen configuration files.

The setup_project tool is safe to re-run — it overwrites existing files with the
latest versions from the server configuration.

## Getting help

- Doen web UI: http://localhost:3000 (or wherever you deployed it)
- Spec contract (what the spec schema looks like): docs/spec-contract.md
- Design principles (why things are the way they are): docs/design-principles.md
"""


@dataclass(frozen=True)
class OnboardingDocument:
    path: str    # relative path within the target project directory
    content: str  # verbatim file content


# The canonical document manifest — edit this list to change what setup_project installs.
# All variants are installed so the user can delete what doesn't apply (discretion item_4030688f3e47).
DOCUMENTS: list[OnboardingDocument] = [
    OnboardingDocument(path="CLAUDE.md", content=_CLAUDE_MD),
    OnboardingDocument(path="agents.md", content=_CLAUDE_MD),
    OnboardingDocument(path="docs/doen-setup.md", content=_DOEN_SETUP_MD),
]

# The prompt the dashboard hint surfaces for copying into an executor.
# The executor (Claude Code etc.) pastes this, which causes it to call setup_project.
SETUP_PROMPT = """\
Set up Doen in this project directory.

Call setup_project(project_path=".") via the Doen MCP server. This installs \
the required Doen configuration files — agent instructions (CLAUDE.md / agents.md), \
and a setup guide (docs/doen-setup.md) — into the current directory.

If setup_project is not yet available, follow the MCP server setup instructions \
at https://github.com/ehtb/doen#mcp-setup to connect your executor first.\
"""
