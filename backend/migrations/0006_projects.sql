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

-- Constraint 6 / a7: the dogfooding project, and assign every existing initiative to it so
-- nothing is orphaned. Idempotent — ON CONFLICT keeps a human-edited intent, and the assign
-- only touches still-unassigned rows (new initiatives stay standalone by default).
INSERT INTO projects (id, name, intent) VALUES (
    'build-doen',
    'Build Doen',
    'Build Doen — the intent layer above agentic executors. Humans author and steer a living '
    'spec for each initiative; executors build against it and surface decisions back. This '
    'project groups every initiative that has built Doen itself — the bootstrap slices and the '
    'dogfooding specs that followed. The strategic goal: a system where deciding what is worth '
    'building and verifying it was built right is the human''s work, the building is the '
    'executor''s, and the two are coordinated through one living spec.'
) ON CONFLICT (id) DO NOTHING;

UPDATE initiatives SET project_id = 'build-doen' WHERE project_id IS NULL;
