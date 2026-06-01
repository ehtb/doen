-- 0012 u5 — sequential, per-project initiative IDs (BD-1, BD-2, …).
-- The internal initiative id (a slug) stays the stable key everything references — MCP, memory,
-- messages, decisions, work units. This adds a short, human identifier on top: a per-project
-- prefix on the project + an immutable, auto-incrementing number on the initiative. Existing rows
-- are backfilled, and each project's initiatives are numbered in creation order so the short id
-- is stable from day one (0012 a10).

-- Projects get a short prefix. Backfill from the name's first letters.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS prefix TEXT;

UPDATE projects SET prefix = upper(left(regexp_replace(name, '[^A-Za-z0-9]', '', 'g'), 2))
WHERE prefix IS NULL;
-- any still-empty (e.g. a name with no letters) -> a stable fallback derived from the id
UPDATE projects SET prefix = upper(left(regexp_replace(id, '[^A-Za-z0-9]', '', 'g'), 2))
WHERE prefix IS NULL OR prefix = '';

ALTER TABLE projects ALTER COLUMN prefix SET NOT NULL;
-- the prefix is the canonical short handle; keep it unique so "BD-7" is unambiguous (a11)
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_prefix ON projects (upper(prefix));

-- Initiatives get an immutable per-project sequence number, assigned in creation order.
ALTER TABLE initiatives ADD COLUMN IF NOT EXISTS seq INTEGER;

WITH ordered AS (
    SELECT id, row_number() OVER (PARTITION BY project_id ORDER BY created_at, id) AS rn
    FROM initiatives
)
UPDATE initiatives i SET seq = o.rn FROM ordered o WHERE i.id = o.id AND i.seq IS NULL;

ALTER TABLE initiatives ALTER COLUMN seq SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_initiatives_project_seq ON initiatives (project_id, seq);
