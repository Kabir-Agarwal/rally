-- ============================================================================
-- Rally batched migration — BLOCK 16: public layer  (SPEC Y3)
-- STATUS: PROPOSED / NOT APPLIED.
-- No session applies schema (SPEC Y5). The owner's chat-Claude applies this via the
--   Supabase MCP (apply_migration), deliberately, after review — build sessions never run it.
-- Engine: public.py (live, deploy.py-preflight-gated). Privacy toggle / Block+Report / age gate wire on the UI.
-- Additive + idempotent (IF NOT EXISTS): a re-apply is safe and prod never breaks (SPEC Y1).
-- Apply after migrations/block-15.sql (ALTERs the accounts table it created) and the identity
--   foundation (references players.id uuid). `players.discoverable` is already added by block-11.
-- ============================================================================

-- The privacy control (public.py PUBLIC/PRIVATE): an account is PUBLIC or PRIVATE. It attaches to the
-- accounts table block-15 created — the column is item #16's, so it lands here, not in block-15.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'public'
  CHECK (visibility IN ('public','private'));

-- The 16+ gate reads a birthday; the Nearby map reads the W3C geolocation permission state. Both hang
-- off the existing player (public.py age_years / can_discover). dob is nullable — an unknown age fails
-- the gate closed (public.py is_old_enough), it is not a default-in row.
ALTER TABLE players ADD COLUMN IF NOT EXISTS dob                 date;
ALTER TABLE players ADD COLUMN IF NOT EXISTS location_permission text NOT NULL DEFAULT 'prompt'
  CHECK (location_permission IN ('prompt','granted','denied'));

-- A block is a DIRECTED edge (public.py: only the blocker can lift it), UNIQUE PER DIRECTION — one row
-- per (blocker, blocked), same shape as feed.follows. The EFFECT is symmetric (is_blocked checks both
-- ways) but that is app logic, not a second row.
CREATE TABLE IF NOT EXISTS blocks (
  blocker    uuid NOT NULL REFERENCES players(id),
  blocked    uuid NOT NULL REFERENCES players(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (blocker, blocked),
  CHECK (blocker <> blocked)          -- public.py: cannot block yourself
);

-- A moderation report (public.py report). The caller stamps id + at. `target` is POLYMORPHIC — the id
-- of whatever surface `kind` names (a player/post/highlight/message/club), so it carries no single FK;
-- `reporter` is always a player. `reason` is required (public.py stores it stripped, non-empty).
CREATE TABLE IF NOT EXISTS reports (
  id       uuid PRIMARY KEY,
  reporter uuid NOT NULL REFERENCES players(id),
  target   uuid NOT NULL,
  kind     text NOT NULL CHECK (kind IN ('player','post','highlight','message','club')),
  reason   text NOT NULL,
  at       timestamptz NOT NULL DEFAULT now()
);
