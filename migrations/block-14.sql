-- ============================================================================
-- Rally batched migration — BLOCK 14: posts feed  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: feed.py (live, deploy.py-preflight-gated). Compose box / follow button / timeline wire on UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/2026-07-27_identity_foundation.sql (references players.id uuid).
-- ============================================================================

-- Following is DIRECTED and asymmetric (feed.py): (follower, followee) is unique PER DIRECTION, so a
-- mutual follow is two distinct rows — deliberately NOT the canonical a<b pair a connection/DM uses.
CREATE TABLE IF NOT EXISTS follows (
  follower   uuid NOT NULL REFERENCES players(id),
  followee   uuid NOT NULL REFERENCES players(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (follower, followee),
  CHECK (follower <> followee)
);

CREATE TABLE IF NOT EXISTS posts (
  id         uuid PRIMARY KEY,
  author     uuid NOT NULL REFERENCES players(id),
  body       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Followed players' MATCHES reuse the existing `matches` rows (feed.py merges posts + matches into
-- one reverse-chronological timeline, each row tagged post/match) — no new match model.
