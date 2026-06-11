-- BD-22 follow-up: persist the latest 'what we know' synthesis on the projects row
-- so it can be returned on every synthesis call, not only during milestone LLM calls.
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS latest_what_we_know JSONB DEFAULT NULL;
