-- 0006_projects — group initiatives under a strategic project (spec 0010, u1).
-- A project is a context boundary for the Advisor (it reasons across the whole project's
-- history). One project per initiative (D1 -> a): a flat nullable FK on the initiative,
-- not a junction table. Global memory search already surfaces cross-project relevance by
-- embedding similarity, so the organisational link stays simple.

CREATE TABLE IF NOT EXISTS projects (
    id         TEXT PRIMARY KEY,           -- slug, derived from the name
    name       TEXT        NOT NULL,
    intent     TEXT        NOT NULL DEFAULT '',  -- the strategic goal, prose
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The link. ADD COLUMN IF NOT EXISTS carries its inline FK, so re-running this migration is
-- a no-op (no duplicate constraint). ON DELETE SET NULL: removing a project orphans nothing —
-- its initiatives simply fall back to standalone, which is a valid state (constraint 1 / a8).
ALTER TABLE initiatives
    ADD COLUMN IF NOT EXISTS project_id TEXT REFERENCES projects(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS initiatives_project_idx ON initiatives (project_id);

