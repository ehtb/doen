# Getting started

From a clean clone to a working Doen instance with an AI-shaped spec in under ten minutes.

**Prerequisites:** Docker (with Compose), a terminal, and an [OpenRouter API key](https://openrouter.ai/keys)
for the AI features. To drive the build loop you'll also want [Claude Code](https://claude.com/claude-code).

## 1. Clone

```bash
git clone https://github.com/ehtb/doen.git
cd doen
```

## 2. Add your API key

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and set two values:

- `LLM_API_KEY` — your OpenRouter key.
- `MCP_TRANSPORT=http` — exposes the MCP server over HTTP so Claude Code can connect to the running container.

## 3. Start the stack

```bash
docker compose up
```

First boot builds the images and starts Postgres (with pgvector), Redis, the backend, and the
web app — running database migrations automatically, no manual step. When the web service is
up, open:

**http://localhost:3000**

You'll land on the home page, showing your projects.

## 4. Create a project

On first visit the Advisor greets you and prompts you to create your first project — a container
for related work. Give it a name (for example, _My product_) and a one-sentence intent, then
click **Create project**.

You land on the project dashboard.

## 5. Shape a spec

Click **New initiative**, give it a title (for example, _Passwordless sign-in_), and create it.
You land in its spec — empty, in the `draft` state.

Click **Shape with AI**. Describe the feature in a few sentences — the problem, who it's for,
what success looks like — and click **Generate spec**.

In a few seconds the AI proposes a full spec: an intent paragraph, constraints, discretion, and
acceptance criteria, all as _proposed_ items (shown dashed — they don't govern yet). Read them,
edit or retire any that miss, and **Confirm** the rest. That's the core move: you're correcting
a knowledgeable first draft, not filling a blank form.

Once all items are confirmed, click **Start building**. The spec is now locked and the initiative
transitions to `building`.

You now have a governing spec. **That's the ten-minute milestone.**

## 6. Connect Claude Code — the executor

With `MCP_TRANSPORT=http` set, the MCP server is available at `http://localhost:8000/mcp/`
once the stack is running.

Add the server to Claude Code — either globally (`~/.claude/settings.json`) or per-project
(`.claude/settings.json` in your codebase):

```json
{
  "mcpServers": {
    "doen": {
      "type": "http",
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

Once the spec is in `building` state, the spec view shows a ready-to-use MCP prompt — click
**Execute** (or **Plan first** to review a build plan before committing). Paste it into Claude
Code. The executor reads the spec, builds against the confirmed acceptance criteria, and submits
evidence back through Doen — all without you writing a brief.

> **Running Claude Code on a different machine?** If Claude Code runs on a remote server or in
> the cloud (e.g. a Railway, Fly, or Render deployment), point it at the backend's public URL
> instead of localhost:
>
> ```json
> {
>   "mcpServers": {
>     "doen": {
>       "type": "http",
>       "url": "https://your-backend.example.com/mcp/"
>     }
>   }
> }
> ```
>
> The trailing slash on `/mcp/` is required. If you're exposing the backend on a raw port without
> a reverse proxy, use `http://your-host:8000/mcp/`. Keep this endpoint on a private network or
> behind a VPC — there is no authentication in front of it yet.

## The full loop

From here, the rest of the loop runs inside Doen:

- **implement** — the executor reads the spec, builds against confirmed acceptance criteria, and submits evidence,
- **verify** — you approve or request changes on the steering rail; the executor re-submits until each criterion is verified,
- **learn** — once every criterion is verified the initiative transitions to `learning`; write the retrospective to close it out and feed its outcomes back into memory.

That's the thesis, running end to end on your machine.
