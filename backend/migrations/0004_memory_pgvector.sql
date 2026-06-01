-- 0004_memory_pgvector — organizational memory substrate (spec 0005, u1).
-- pgvector lands here (0001 deferred it to "the memory spec"). decisions get an
-- embedding so resolved judgments become retrievable; a new append-only `memory`
-- table holds a completed initiative's outcome + learnings. Dimension is 1536 to
-- match the dogfooding default provider (openai/text-embedding-3-small); a self-
-- hoster swapping the model writes a follow-up migration to change it.

CREATE EXTENSION IF NOT EXISTS vector;

-- Resolved decisions are the highest-value context (the reasoning behind a call).
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Append-only: one row per completed (or revisited) initiative. Never edited —
-- a fresh revisit becomes a new row, not an overwrite (constraint 4).
CREATE TABLE IF NOT EXISTS memory (
    id            TEXT PRIMARY KEY,
    initiative_id TEXT        NOT NULL REFERENCES initiatives(id) ON DELETE CASCADE,
    summary       TEXT        NOT NULL,
    learnings     TEXT,
    outcome       JSONB,
    embedding     vector(1536),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_initiative_idx ON memory (initiative_id);

-- HNSW + cosine: builds on an empty table (no training pass like IVFFlat), good
-- default at this scale. get_context (u3) orders by `embedding <=> query`.
CREATE INDEX IF NOT EXISTS decisions_embedding_idx
    ON decisions USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS memory_embedding_idx
    ON memory USING hnsw (embedding vector_cosine_ops);
