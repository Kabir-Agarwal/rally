-- ============================================================================
-- Rally batched migration — BLOCK 15: org / club accounts  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: orgs.py (live, deploy.py-preflight-gated). Club profile / roster / manage wire on the UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/2026-07-27_identity_foundation.sql (references players.id uuid).
-- ============================================================================

-- An account is a public identity with a real membership ladder (orgs.py). Handle UNIQUENESS is the
-- DB's job — orgs.normalize_handle validates the shape and leaves the collision to this unique index.
CREATE TABLE IF NOT EXISTS accounts (
  id         uuid PRIMARY KEY,
  name       text NOT NULL,
  handle     text NOT NULL UNIQUE,
  kind       text NOT NULL CHECK (kind IN ('club','org')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Roles are a ladder owner > admin > member, unique per (org, player).
CREATE TABLE IF NOT EXISTS memberships (
  org    uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  player uuid NOT NULL REFERENCES players(id),
  role   text NOT NULL CHECK (role IN ('owner','admin','member')),
  PRIMARY KEY (org, player)
);

-- The "exactly one owner always" invariant is held by construction in the orgs.py role engine
-- (found seeds one owner, transfer is the only move, nothing deletes it) — not a DB constraint.
