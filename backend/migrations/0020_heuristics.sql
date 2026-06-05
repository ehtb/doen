-- BD-17: heuristics as a first-class memory type — append-only with supersession chain.
-- Stored in a separate table from memory (narrative/decision) per constraint item_5358c84c18fc.
-- Append-only: superseded_by is set when a newer heuristic replaces this one; the old row
-- stays readable. replaces records the heuristic_id this entry supersedes (bi-directional chain
-- per constraint item_47ba758192ea).

CREATE TABLE IF NOT EXISTS heuristics (
    id              TEXT PRIMARY KEY,
    initiative_id   TEXT        NOT NULL REFERENCES initiatives(id) ON DELETE CASCADE,
    project_id      TEXT        REFERENCES projects(id) ON DELETE CASCADE,
    rule            TEXT        NOT NULL,
    tags            TEXT[]      NOT NULL DEFAULT '{}',
    superseded_by   TEXT,           -- initiative_id that superseded this entry
    replaces        TEXT,           -- heuristic_id this entry replaces (back-reference)
    embedding       vector(1536),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS heuristics_initiative_idx  ON heuristics(initiative_id);
CREATE INDEX IF NOT EXISTS heuristics_project_idx     ON heuristics(project_id);
CREATE INDEX IF NOT EXISTS heuristics_active_idx      ON heuristics(project_id)
    WHERE superseded_by IS NULL;

-- HNSW index for fast approximate similarity search on active heuristics.
CREATE INDEX IF NOT EXISTS heuristics_embedding_idx
    ON heuristics USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL AND superseded_by IS NULL;
