-- 0002_work_units — tracked, bounded units decomposed from a spec (spec 0003).
-- Units are their OWN table, not inside the spec JSONB: they churn at a different
-- frequency (progress, status transitions) and must not share the spec's version
-- lock (constraint 1). The whole unit is a jsonb payload (like specs.doc /
-- decisions.payload); spec_id + status are promoted to columns so
-- list_units(spec_id, status?) is a plain indexed query.
--
-- spec_id holds the initiative_id (one spec per initiative). The FK cascades:
-- dropping an initiative drops its spec, which drops its work units.

CREATE TABLE IF NOT EXISTS work_units (
    id         TEXT PRIMARY KEY,
    spec_id    TEXT        NOT NULL REFERENCES specs(initiative_id) ON DELETE CASCADE,
    payload    JSONB       NOT NULL,
    status     TEXT        NOT NULL DEFAULT 'proposed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS work_units_spec_idx ON work_units (spec_id, status);
