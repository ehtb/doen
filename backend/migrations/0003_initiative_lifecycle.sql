-- 0003_initiative_lifecycle — make `initiatives` a first-class parent (spec 0004).
-- The table already exists (0001_init) as the FK parent for specs; this gives it a
-- human title + an updated_at, relaxes the unused ownership columns to nullable until
-- auth (0007), and backfills title + stage from each initiative's spec so the specs
-- seeded before this slice are not left blank or stage-desynced.

ALTER TABLE initiatives ADD COLUMN IF NOT EXISTS title      TEXT;
ALTER TABLE initiatives ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE initiatives ALTER COLUMN org_id   DROP NOT NULL;
ALTER TABLE initiatives ALTER COLUMN owner_id DROP NOT NULL;

-- Backfill from the spec: fill a missing title, and sync the lifecycle stage to the
-- spec's current stage. Idempotent — safe to re-run.
UPDATE initiatives i
   SET title = COALESCE(i.title, s.doc ->> 'title'),
       stage = COALESCE(s.doc ->> 'stage', i.stage)
  FROM specs s
 WHERE s.initiative_id = i.id;
