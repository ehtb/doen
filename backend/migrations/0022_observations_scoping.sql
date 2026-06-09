-- BD-24: Scope observations to the most recently completed initiative and add reject flow.
-- source_initiative_id: which initiative this observation was generated for.
-- Unique index (WHERE NOT NULL) enforces one observation per initiative lifetime.
-- 'rejected' added to the status enum so a human can dismiss without acting.

ALTER TABLE observations
  ADD COLUMN source_initiative_id TEXT REFERENCES initiatives(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS observations_one_per_initiative
  ON observations(source_initiative_id)
  WHERE source_initiative_id IS NOT NULL;

ALTER TABLE observations DROP CONSTRAINT observations_status_check;
ALTER TABLE observations ADD CONSTRAINT observations_status_check
  CHECK (status IN ('open', 'resolved', 'rejected'));
