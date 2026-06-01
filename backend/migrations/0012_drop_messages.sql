-- 0012_drop_messages — conversations leave Postgres for the browser (spec uvama, u1).
-- Conversations are now a session concern, stored client-side in IndexedDB, not a durable
-- server artifact. Raw messages were pre-auth shared state with no user ownership, so there
-- is nothing worth migrating — the table is dropped outright, no data transfer. The valuable
-- outcomes of a conversation (spec items, decisions, memory) already live in their own tables
-- and are untouched. The backend is now stateless about conversation history: the frontend
-- sends a windowed slice with each Advisor call and the backend discards it after replying.
--
-- This also (by decision dec_0397d7a8f45e, option A) retires the message-derived MCP enrichment
-- that read this table: get_spec's advisor_summary + per-unit advisor_review and
-- get_conversation_summary's stated_priorities degrade to null/empty rather than crash.

DROP TABLE IF EXISTS messages;
