-- 0013 follow-up: soft-archive for initiatives. Reject (from draft) and Archive (from building
-- or complete) share one mechanism — a non-null archived_at hides the initiative from every
-- list that drives the dashboards, while the spec, units, decisions, and memory stay on disk so
-- an unarchive (DB write) is a clean restore. The optional reason names why ("rejected" or
-- "archived"); free text is allowed for future extensions.

ALTER TABLE initiatives
  ADD COLUMN IF NOT EXISTS archived_at      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS archived_reason  TEXT;

-- partial index: the hot path is "active initiatives only", and the small "archived" set is
-- read rarely. The partial form keeps the index tight and the active scan fast.
CREATE INDEX IF NOT EXISTS idx_initiatives_active
  ON initiatives (project_id, updated_at DESC)
  WHERE archived_at IS NULL;
