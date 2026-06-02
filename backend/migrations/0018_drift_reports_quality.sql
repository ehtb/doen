-- BD-12 follow-up: LLM-as-judge quality evaluation on drift reports.
-- Stores per-dimension scores + overall + feedback as JSONB so the result is queryable
-- and survives schema evolution without another migration.

ALTER TABLE drift_reports ADD COLUMN IF NOT EXISTS quality JSONB;
