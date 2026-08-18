-- ============================================================================
-- Rally batched migration — BLOCK 13: highlights  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: highlights.py (live, deploy.py-preflight-gated). Upload form / player / stars wire on UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/2026-07-27_identity_foundation.sql (references players.id uuid).
-- ============================================================================

-- A highlight is a LANDSCAPE clip (highlights.accept_upload gates dims/format/size/duration). The
-- laurel (none/bronze/silver/gold) is DERIVED from the ratings below (highlights.laurel), so it is
-- not a stored column — it recomputes on read, the same earned-from-0 principle as the card stats.
CREATE TABLE IF NOT EXISTS highlights (
  id         uuid PRIMARY KEY,
  owner      uuid NOT NULL REFERENCES players(id),
  url        text NOT NULL,
  width      integer NOT NULL,
  height     integer NOT NULL,
  duration_s numeric NOT NULL,
  size_bytes bigint  NOT NULL,
  format     text    NOT NULL,
  aspect     numeric,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (width > height)          -- landscape (accept_upload enforces it; the DB backstops it)
);

-- Viewers rate 1-5 stars; unique (highlight, viewer) makes re-rating an upsert (one vote/viewer) and
-- highlights.rate() refuses rating your own clip. reputation() aggregates average + count from here.
CREATE TABLE IF NOT EXISTS highlight_ratings (
  highlight uuid NOT NULL REFERENCES highlights(id) ON DELETE CASCADE,
  viewer    uuid NOT NULL REFERENCES players(id),
  stars     integer NOT NULL CHECK (stars BETWEEN 1 AND 5),
  PRIMARY KEY (highlight, viewer)
);
