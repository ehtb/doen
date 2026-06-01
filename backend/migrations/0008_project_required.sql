-- 0008_project_required — every initiative belongs to a project; no orphan specs.
-- project_id is made NOT NULL; the FK switches from ON DELETE SET NULL to ON DELETE RESTRICT
-- so a project can't be deleted while it still owns initiatives.

ALTER TABLE initiatives ALTER COLUMN project_id SET NOT NULL;

ALTER TABLE initiatives DROP CONSTRAINT IF EXISTS initiatives_project_id_fkey;
ALTER TABLE initiatives ADD CONSTRAINT initiatives_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
