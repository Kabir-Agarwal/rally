-- ============================================================================
-- Rally batched migration — BLOCK 11: nearby players  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: nearby.py (live, deploy.py-preflight-gated). Map + Connect button wire on the UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/2026-07-27_identity_foundation.sql (uses the friendships table it created).
-- ============================================================================

-- A player appears on the map only with a location AND an explicit opt-in (nearby.py).
ALTER TABLE players ADD COLUMN IF NOT EXISTS lat          double precision;
ALTER TABLE players ADD COLUMN IF NOT EXISTS lng          double precision;
ALTER TABLE players ADD COLUMN IF NOT EXISTS discoverable boolean NOT NULL DEFAULT false;

-- Connections are NOT a new table: nearby.py keys them on the existing `friendships` shape
-- (a_id < b_id, status pending -> accepted, requested_by) that the identity foundation already
-- created. "Connect" and "Message" both reuse it — one pair, one row. Privacy/permission on lat/lng
-- (location-permission handling, 16+ gate) is the public layer's job (item #16), not this column.
