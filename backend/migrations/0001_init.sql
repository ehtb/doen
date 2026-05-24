-- 0001_init — the relational surface for the self-hosting slice.
-- Postgres is the source of truth. The spec is ONE jsonb document per initiative
-- (specs.doc); decisions are durable rows alongside it. No pgvector / embedding
-- columns in this slice (spec 0001 bans them) — they arrive with the memory spec.

CREATE TABLE IF NOT EXISTS initiatives (
    id         TEXT PRIMARY KEY,
    org_id     TEXT        NOT NULL,
    owner_id   TEXT        NOT NULL,
    appetite   TEXT,
    stage      TEXT        NOT NULL DEFAULT 'shape',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per initiative: the whole living spec as a single jsonb document.
-- version is the optimistic lock (see SpecStore.save_spec).
CREATE TABLE IF NOT EXISTS specs (
    initiative_id TEXT PRIMARY KEY REFERENCES initiatives(id) ON DELETE CASCADE,
    version       INTEGER     NOT NULL,
    doc           JSONB       NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only judgment log; individually addressable, surfaced over MCP in u3.
CREATE TABLE IF NOT EXISTS decisions (
    id            TEXT PRIMARY KEY,
    initiative_id TEXT        NOT NULL REFERENCES initiatives(id) ON DELETE CASCADE,
    payload       JSONB       NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'open',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS decisions_initiative_idx ON decisions (initiative_id);
