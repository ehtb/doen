SHELL := /bin/bash

# Doen local dev. `make` (or `make dev`) brings up infra, applies migrations,
# then runs the backend (:8000) and web (:3000) together. Ctrl-C stops both.
# The MCP server is stdio and launched on demand by Claude Code, not here.

.DEFAULT_GOAL := dev
.PHONY: dev infra migrate backend web seed down logs

dev: infra migrate
	@echo "→ backend http://localhost:8000  ·  web http://localhost:3000  (Ctrl-C stops both)"
	@trap 'kill 0' EXIT INT TERM; \
	( cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000 ) & \
	( cd web && npm run dev ) & \
	wait

infra:
	docker compose up -d --wait

migrate:
	cd backend && .venv/bin/python -m app.migrate

seed:
	cd backend && .venv/bin/python -m app.seed

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web:
	cd web && npm run dev

down:
	docker compose down

logs:
	docker compose logs -f
