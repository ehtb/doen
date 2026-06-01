-- 0005_conversation — the conversation rail's persisted history (spec 0009, u1).
-- One row per message (constraint 1: individual rows, never a JSONB blob). The rail
-- replays the full history; the Advisor's LLM calls (u2) read only a recent window,
-- assembled with the current spec + relevant memory. `metadata` carries structured
-- payloads like the Advisor's proposal cards. `seq` gives a stable total order even
-- when two messages share a created_at (a human turn + its Advisor reply).

CREATE TABLE IF NOT EXISTS messages (
    seq           BIGSERIAL,
    id            TEXT PRIMARY KEY,
    initiative_id TEXT        NOT NULL REFERENCES initiatives(id) ON DELETE CASCADE,
    role          TEXT        NOT NULL,
    content       TEXT        NOT NULL,
    metadata      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The rail reads one initiative's history in insertion order; the window query (u2)
-- takes the newest N. The composite serves both.
CREATE INDEX IF NOT EXISTS messages_initiative_seq_idx
    ON messages (initiative_id, seq);
