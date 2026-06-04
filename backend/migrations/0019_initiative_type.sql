-- BD-15: initiative types (engineering / research). Two columns:
-- 1. initiatives.initiative_type — persists the type chosen at creation; immutable.
-- 2. memory.initiative_type — mirrors the originating initiative's type so context
--    hits can expose whether a learning came from research or engineering.
ALTER TABLE initiatives
    ADD COLUMN IF NOT EXISTS initiative_type TEXT NOT NULL DEFAULT 'engineering';

ALTER TABLE memory
    ADD COLUMN IF NOT EXISTS initiative_type TEXT NOT NULL DEFAULT 'engineering';
