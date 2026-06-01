# Doen — Deployment Guide

This guide covers everything needed to run Doen in production: prerequisites, environment
configuration, container images, migrations, and connecting Claude Code over HTTP MCP so a
remote engineer's agent can build against specs authored in the browser.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker | 24+ | with Compose v2 (`docker compose`) |
| Managed Postgres | 15+ | **pgvector extension required** |
| Redis | 6.0+ | pub/sub and keyspace notifications used |

### Postgres providers with pgvector

Any provider that lets you enable the `pgvector` extension works. Confirmed options:

- **Supabase** — pgvector enabled by default
- **Neon** — pgvector available on all plans (`CREATE EXTENSION vector`)
- **Render Managed Postgres** — pgvector available via extension install
- **DigitalOcean Managed Postgres** — pgvector on all plans
- **Railway** — pgvector available
- **AWS RDS / Aurora** — `pgvector` extension available from Postgres 15

After provisioning, verify: `SELECT extversion FROM pg_extension WHERE extname = 'vector';`

### Minimum Redis features

Doen uses pub/sub (decision notifications) and standard key/value caching. Redis 6.0+
covers all required features. No special modules needed (no RediSearch, no RedisJSON).

---

## Environment configuration

Copy `.env.example` to `.env` and fill in every value:

```bash
cp .env.example .env
```

The file is grouped by category with inline comments. Key variables:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Postgres connection string (include `?sslmode=require` for managed providers) |
| `REDIS_URL` | Yes | Redis connection string (`rediss://` for TLS) |
| `OPENROUTER_API_KEY` | Yes | Powers spec shaping (Claude) and embeddings |
| `MCP_TRANSPORT` | Yes | `stdio` or `http` — see MCP section below |
| `SHAPING_MODEL` | No | Default: `anthropic/claude-sonnet-4.6` |
| `EMBEDDING_MODEL` | No | Default: `openai/text-embedding-3-small` |
| `EMBEDDING_DIM` | No | Default: `1536` (must match the model's output) |
| `LOG_LEVEL` | No | Default: `info` |

---

## Dev vs. production — which compose to use

| File | Use when |
|---|---|
| `docker-compose.yml` | Local development — includes local Postgres and Redis containers |
| `docker-compose.prod.yml` | Production — backend and web only; external DB and Redis |

The dev compose is unaffected by this deployment setup. Running `docker compose up` (the
dev default) continues to work exactly as before with no additional configuration.

---

## Building and starting the production stack

```bash
# Build both images
docker compose -f docker-compose.prod.yml build

# Start in the background (migrations run automatically on backend startup)
docker compose -f docker-compose.prod.yml up -d

# Tail logs
docker compose -f docker-compose.prod.yml logs -f
```

The backend starts, runs pending migrations against the external Postgres, then serves
on port 8000. The web frontend starts on port 3000 after the backend passes its health
check.

---

## Running migrations

Migrations run automatically when the backend container starts (via `python -m app.migrate`
in the container CMD). They are forward-only and idempotent — safe to re-run.

To run migrations manually without starting the server (e.g. on a fresh database):

```bash
docker compose -f docker-compose.prod.yml run --rm backend python -m app.migrate
```

After running, verify the schema:

```sql
-- Connect to your managed Postgres and check tables exist
SELECT tablename FROM pg_tables WHERE schemaname = 'public';

-- Confirm pgvector is active
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

---

## Health checks

**Backend** — `GET /health` returns:

```json
{ "status": "ok", "postgres": true, "redis": true }
```

- HTTP 200 when Postgres and Redis are both reachable
- HTTP 503 with `"status": "degraded"` when either dependency is down

**Web** — `GET /api/health` returns HTTP 200 `{ "status": "ok" }`.

Both are wired into the docker-compose health checks and suitable for load balancer probes.

---

## Connecting Claude Code via HTTP MCP

> **Security warning:** HTTP MCP is intended for VPC/private network deployment only.
> Do not expose port 8000 to the public internet without adding authentication (planned
> in spec 0007). The VPC network boundary is the sole trust mechanism in this release.

### 1. Enable HTTP transport

In your production `.env`, set:

```
MCP_TRANSPORT=http
```

Restart the backend. The MCP server is now served at `http://<backend-host>:8000/mcp`
alongside the REST API — same process, same port, no extra service.

### 2. Configure Claude Code on the engineer's machine

Add a `doen` server to the engineer's `.mcp.json` (project-level) or
`~/.claude/mcp.json` (user-level):

```json
{
  "mcpServers": {
    "doen": {
      "url": "http://<backend-host>:8000/mcp"
    }
  }
}
```

Replace `<backend-host>` with the private IP or hostname of the machine running the
production stack (reachable from within the VPC).

### 3. Verify the connection

In a Claude Code session, call `get_spec` for any initiative. A valid spec response
confirms the HTTP MCP endpoint is reachable and the tools work correctly.

### Local dev (stdio — unchanged)

For local development, the MCP server continues to run as a subprocess via:

```bash
docker compose exec -T backend python -m app.mcp_server
```

This is wired into the project's `.mcp.json` and requires no configuration changes.

---

## Reverse proxy (optional)

The production compose exposes the backend on port 8000 and the web on port 3000.
If you want TLS termination or a single ingress point, put a reverse proxy (nginx,
Caddy, Traefik) in front of both services. The compose file does not include one —
the deployer provides it externally.

Example Caddyfile snippet:

```
doen.example.com {
    reverse_proxy /api/* localhost:8000
    reverse_proxy /mcp   localhost:8000
    reverse_proxy /*     localhost:3000
}
```

---

## Production checklist

- [ ] Managed Postgres provisioned with pgvector (`CREATE EXTENSION IF NOT EXISTS vector`)
- [ ] Redis provisioned (6.0+)
- [ ] `.env` created from `.env.example` with all values filled
- [ ] `OPENROUTER_API_KEY` set
- [ ] `DATABASE_URL` includes SSL (`?sslmode=require`)
- [ ] `MCP_TRANSPORT=http` if enabling remote Claude Code access
- [ ] Backend port 8000 accessible only within the VPC (not public internet)
- [ ] `docker compose -f docker-compose.prod.yml build` succeeds
- [ ] `docker compose -f docker-compose.prod.yml up -d` starts both services
- [ ] `GET /health` returns HTTP 200
- [ ] `GET /api/health` returns HTTP 200
