-- BD-12: Reflexive Memory Verification via MCP
-- Adds last_verified_at to memory (for audit staleness filtering) and creates the
-- drift_reports table (agent-reported discrepancies, human-gated before memory mutation).

ALTER TABLE memory ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS drift_reports (
    id               TEXT        PRIMARY KEY,
    memory_id        TEXT        NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
    initiative_id    TEXT,
    current_evidence TEXT        NOT NULL,
    is_obsolete      BOOLEAN     NOT NULL DEFAULT FALSE,
    status           TEXT        NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','approved','dismissed','initiative_created')),
    resolution_note  TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS drift_reports_memory_id_idx ON drift_reports(memory_id);
CREATE INDEX IF NOT EXISTS drift_reports_status_idx    ON drift_reports(status);
