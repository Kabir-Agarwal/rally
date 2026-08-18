-- ============================================================================
-- Rally batched migration — BLOCK 20: Y6 Tier-1 video stats  (SPEC Y6)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: video.py (live, deploy.py-preflight-gated). The laptop tool produces the stats JSON that
--   lands here; its highlight CLIPS land in the existing `highlights` table (block-13).
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/block-16.sql (references players(id) uuid, matches(id) text).
-- ============================================================================

-- SPEC Y6: the laptop-only tool uploads ONLY the stats JSON + highlight clips — never the raw match
-- video. This is the home for that stats JSON (video.analyze() payload: rally spans, counts/lengths,
-- highlight-reel spans, movement heatmap, capture guidance). Stored whole as jsonb — the tool owns the
-- shape and it recomputes off the laptop, so there is nothing here to keep in sync with the engine.
CREATE TABLE IF NOT EXISTS video_stats (
  id         uuid PRIMARY KEY,
  owner      uuid NOT NULL REFERENCES players(id),
  match      text REFERENCES matches(id),   -- OPTIONAL: link to a logged match if there is one (a
                                            -- highlight video need not be a scored match)
  stats      jsonb NOT NULL,                -- the whole video.analyze() Tier-1 payload
  created_at timestamptz NOT NULL DEFAULT now()
);

-- One owner reads back their own analyses newest-first on the match / highlights screen (a follow-on
-- wiring item flips that screen dummy -> live); the clips themselves are rows in `highlights`.
CREATE INDEX IF NOT EXISTS video_stats_owner_idx ON video_stats (owner, created_at DESC);
