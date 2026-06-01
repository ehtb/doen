-- BD-9: track whether the project's onboarding hint has been dismissed per-project, server-side.
-- Constraint: dismissal must not rely on localStorage or client state (item_b8b031fbfe0f).
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS onboarding_dismissed BOOLEAN NOT NULL DEFAULT FALSE;
