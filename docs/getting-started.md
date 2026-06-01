# Getting started

From a clean clone to a working Doen instance with an AI-shaped spec in under ten minutes.

**Prerequisites:** Docker (with Compose), a terminal, and an [OpenRouter API key](https://openrouter.ai/keys)
for the AI features. To drive the build loop you'll also want [Claude Code](https://claude.com/claude-code).

## 1. Clone

```bash
git clone https://github.com/doen-dev/doen.git
cd doen
```

## 2. Add your API key

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and set `LLM_API_KEY` to your key. That's the only value you need to
change — Compose wires up the database and Redis for you.

## 3. Start the stack

```bash
docker compose up
```

First boot builds the images and starts Postgres (with pgvector), Redis, the backend, and the
web app — running database migrations automatically, no manual step. When the web service is
up, open:

**http://localhost:3000**

You'll land on an empty dashboard.

## 4. Create an initiative

Click **New initiative**, give it a title (for example, *Passwordless sign-in*), and create it.
You land in its spec — empty, at the `discover` stage.

## 5. Shape a spec with AI

In the spec view, click **Shape with AI**. Describe the feature in a few sentences — the
problem, who it's for, what success looks like — and click **Generate spec**.

In a few seconds the AI proposes a full spec: an intent paragraph, constraints, discretion, and
acceptance criteria, all as *proposed* items (shown dashed — they don't govern yet). Read them,
edit or retire any that miss, and **Confirm** the rest. That's the core move: you're correcting
a knowledgeable first draft, not filling a blank form.

You now have a governing spec. **That's the ten-minute milestone.**

## 6. Connect Claude Code — the executor

Doen exposes its spec, decisions, work units, and memory to an executor over an MCP server.
The repo ships a `.mcp.json` configured for the Docker setup:

```json
{
  "mcpServers": {
    "doen": {
      "type": "stdio",
      "command": "docker",
      "args": ["compose", "exec", "-T", "backend", "python", "-m", "app.mcp_server"]
    }
  }
}
```

With `docker compose up` running, open the repo in Claude Code from the repo root. Claude Code
launches the MCP server inside the backend container, sharing your database. Ask it to
`get_spec` for your initiative — it reads the spec you just shaped, and can propose work units,
report progress, and raise decisions, all back through Doen.

> **Running the backend on your host instead** (`make dev`, no containers)?
> The backend reads `backend/.env`. Point `.mcp.json` at the local interpreter:
> ```json
> {
>   "mcpServers": {
>     "doen": {
>       "type": "stdio",
>       "command": "./backend/.venv/bin/python",
>       "args": ["-m", "app.mcp_server"],
>       "env": { "PYTHONPATH": "./backend" }
>     }
>   }
> }
> ```

> **Running Claude Code on a different machine?** Use HTTP transport instead of stdio.
> Set `MCP_TRANSPORT=http` in `backend/.env`, restart the stack, then point `.mcp.json` at
> the backend URL:
> ```json
> {
>   "mcpServers": {
>     "doen": {
>       "type": "http",
>       "url": "https://doen.example.com/mcp/"
>     }
>   }
> }
> ```
> The MCP server mounts at `/mcp/` on the FastAPI app (trailing slash required). If
> you're exposing the backend directly without a reverse proxy, use port 8000
> (e.g. `http://your-host:8000/mcp/`). Keep this on a private network — there is no
> authentication in front of it yet.

## The full loop

From here, the rest of the loop runs inside Doen:

- **decompose** the spec into work units (the executor proposes them; you confirm),
- **implement** — the executor claims a unit, builds, and submits it with per-criterion evidence,
- **verify** — you approve or request changes against the acceptance criteria,
- **learn** — advance to the Learn stage and capture the outcome; it's embedded into memory, and
  the next initiative you shape will retrieve it.

That's the thesis, running end to end on your machine.
