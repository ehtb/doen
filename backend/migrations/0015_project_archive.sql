-- BD-11: first-class archived state for projects (constraint item_cef8f182b12e).
-- NULL = active; a timestamp = archived at that instant.
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
