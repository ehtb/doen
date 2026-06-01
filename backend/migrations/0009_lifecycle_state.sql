-- 0011 u1 — replace the 7-stage lifecycle with 3 inferred states (Draft / Building / Complete).
-- The state is inferred from work units + learn (never advanced by hand), but it is stored so the
-- project screen + dashboard can group cheaply, and so existing initiatives keep the correct
-- position. Migration maps the old stage: discover/shape/bet/decompose -> draft, implement/verify
-- -> building, learn -> complete (0011 a1, discretion on migration).

ALTER TABLE initiatives ADD COLUMN IF NOT EXISTS state TEXT NOT NULL DEFAULT 'draft';

UPDATE initiatives SET state = CASE
    WHEN stage IN ('implement', 'verify') THEN 'building'
    WHEN stage = 'learn' THEN 'complete'
    ELSE 'draft'
END;

-- Rewrite the JSONB spec docs: rename the `stage` key to `state` with the same mapping. The Spec
-- model is extra='forbid', so a leftover `stage` key would fail to load — the key must be renamed.
UPDATE specs SET doc = (doc - 'stage') || jsonb_build_object('state', CASE
    WHEN doc->>'stage' IN ('implement', 'verify') THEN 'building'
    WHEN doc->>'stage' = 'learn' THEN 'complete'
    ELSE 'draft'
END);

ALTER TABLE initiatives DROP COLUMN stage;

CREATE INDEX IF NOT EXISTS idx_initiatives_state ON initiatives (state);
