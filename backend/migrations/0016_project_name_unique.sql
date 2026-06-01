-- BD-11: project names must be unique (case-insensitive). The ID is just the name slug,
-- so a duplicate name would produce a duplicate ID — enforce it at the source instead.
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name ON projects (lower(name));
