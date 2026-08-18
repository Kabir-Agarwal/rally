-- ============================================================================
-- Rally batched migration — BLOCK 10: competitions hub  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: competitions.py (live, deploy.py-preflight-gated). Create/Manage forms wire on the UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/2026-07-27_identity_foundation.sql (references players.id uuid).
-- ============================================================================

-- A competition names a FORMAT and moves forward through the lifecycle draft -> open -> scheduled
-- -> live -> completed (competitions.py). The four hub sections derive from `status`, not stored.
CREATE TABLE IF NOT EXISTS competitions (
  id         uuid PRIMARY KEY,
  format     text NOT NULL CHECK (format IN ('tournament','league')),
  status     text NOT NULL DEFAULT 'draft'
             CHECK (status IN ('draft','open','scheduled','live','completed')),
  name       text,
  starts_at  timestamptz,                              -- required before a comp can be Scheduled
  created_by uuid REFERENCES players(id),              -- the owner who advances / reviews it
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS competition_entrants (
  competition_id uuid NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
  player_id      uuid NOT NULL REFERENCES players(id),
  seed           integer,
  PRIMARY KEY (competition_id, player_id)
);

-- The live bracket / round-robin structure competitions.start() builds is NOT persisted here: it
-- maps onto the existing `matches` model when the hub screen goes live (a follow-on wiring item),
-- so no bracket table is invented now — the tournaments/leagues engines recompute rounds from
-- results. Tournaments (#7) and leagues (#8) persist through this same competitions block.
