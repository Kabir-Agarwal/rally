-- ============================================================================
-- Rally batched migration — BLOCK 12: messenger  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: messenger.py (live, deploy.py-preflight-gated). Thread/inbox + smart-reply wire on the UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/2026-07-27_identity_foundation.sql (references players.id uuid).
-- ============================================================================

-- A conversation is one unordered pair, keyed exactly like a connection (messenger.pair_key — the
-- friendships shape, a_id < b_id). `read` is whether the RECIPIENT has seen it. The AI smart-reply
-- helper is a stateless keyword heuristic (messenger.classify) — nothing to persist for it.
CREATE TABLE IF NOT EXISTS messages (
  id      uuid PRIMARY KEY,
  a_id    uuid NOT NULL REFERENCES players(id),   -- conversation pair, canonical a_id < b_id
  b_id    uuid NOT NULL REFERENCES players(id),
  sender  uuid NOT NULL REFERENCES players(id),   -- one of the pair
  body    text NOT NULL,
  sent_at timestamptz NOT NULL DEFAULT now(),
  read    boolean NOT NULL DEFAULT false,
  CHECK (a_id < b_id),
  CHECK (sender = a_id OR sender = b_id)
);

-- Thread reads (a conversation, oldest-first) and the inbox both scan by pair then time.
CREATE INDEX IF NOT EXISTS messages_pair_time ON messages (a_id, b_id, sent_at);
