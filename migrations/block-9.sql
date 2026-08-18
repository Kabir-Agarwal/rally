-- ============================================================================
-- Rally batched migration — BLOCK 9: practice-vs-rated split  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: practice.py (live, deploy.py-preflight-gated). Log-a-game toggle wires on the UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/2026-07-27_identity_foundation.sql.
-- ============================================================================

ALTER TABLE matches
  ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'rated'
  CHECK (mode IN ('rated','practice'));

-- Back-compat: every existing row defaults to 'rated' == practice.DEFAULT_MODE, so each counted
-- match keeps feeding the Elo rating byte-for-byte (practice.py: absent/None mode reads as rated).
-- The split is purely additive — a practice match is logged but never touches the rating.
