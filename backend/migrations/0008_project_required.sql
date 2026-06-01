-- 0008_project_required — every initiative belongs to a project; no orphan specs.
-- This supersedes 0010's original nullable-project carve-out: a spec without a project is no
-- longer a valid state. Backfill any straggler to the dogfooding project, make project_id NOT
-- NULL, and switch the FK from ON DELETE SET NULL (which only made sense for nullable) to
-- ON DELETE RESTRICT — a project can't be deleted while it still owns initiatives.

UPDATE initiatives SET project_id = 'build-doen' WHERE project_id IS NULL;

ALTER TABLE initiatives ALTER COLUMN project_id SET NOT NULL;

ALTER TABLE initiatives DROP CONSTRAINT IF EXISTS initiatives_project_id_fkey;
ALTER TABLE initiatives ADD CONSTRAINT initiatives_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
