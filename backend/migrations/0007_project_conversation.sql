-- 0007_project_conversation — the project-level rail's persisted history (spec 0010, u5).
-- The same Advisor, scoped to the whole project (D2 -> a), talks on the project dashboard.
-- Reuse the 0009 `messages` table rather than a parallel one: a message now belongs to EITHER
-- an initiative OR a project (exactly one), so the rail component, the Message model, and the
-- windowing all stay single-sourced. Existing rows are initiative-owned and untouched.

ALTER TABLE messages ALTER COLUMN initiative_id DROP NOT NULL;
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS project_id TEXT REFERENCES projects(id) ON DELETE CASCADE;

-- exactly one owner — an initiative message or a project message, never both/neither.
DO $$ BEGIN
    ALTER TABLE messages ADD CONSTRAINT messages_owner_chk CHECK (
        (initiative_id IS NOT NULL AND project_id IS NULL)
        OR (initiative_id IS NULL AND project_id IS NOT NULL)
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- the project rail reads one project's history in order; the window query takes the newest N.
CREATE INDEX IF NOT EXISTS messages_project_seq_idx ON messages (project_id, seq);
