-- ============================================================================
-- Rally — identity foundation migration  (2026-07-27-FOUNDATION, Task 3)
-- STATUS: PROPOSED / NOT APPLIED.  Do NOT run against production until the owner
--   (a) resolves the DECISIONS below and (b) explicitly approves.
-- Target: Supabase Postgres project ref kmaqprycvhngzrykebaa.
-- Apply deliberately via Supabase MCP (never the app's silent auto-migration),
--   inside ONE transaction, verifying counts after each step, against a backup/branch first.
--
-- WHY THIS IS NOT A ONE-CLICK SCRIPT: the current live model keys identity on a
--   per-group INTEGER players.id (a human in N groups = N rows) linked to an auth
--   user via player_links(group_id, auth_sub -> player_id). Task 3 wants ONE GLOBAL
--   player = auth.users(id) (uuid) with membership via group_members. Collapsing the
--   old rows into one global row is genuinely ambiguous — see DECISIONS D1–D4. The
--   ADDITIVE parts (Section 1) are safe; the DATA MIGRATION (Section 3) is gated.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- DECISIONS THE OWNER MUST MAKE BEFORE SECTION 3 RUNS (cannot be guessed):
--   D1  game_name on merge: a user with different names in different groups collapses
--       to ONE global game_name. Which wins? (most-recent link / a named "home" group /
--       prompt each user). name_history should capture the losers.
--   D2  UNLINKED players (admin-created, never claimed by an auth user) have NO
--       auth.users(id). Task 3 says players.id references auth.users(id) NOT NULL, so
--       they cannot become players. Options: (a) mint shadow auth users, (b) keep them
--       as non-account "roster entries" in a separate table, (c) drop them (loses their
--       match history unless remapped). MUST decide — this blocks the literal spec.
--   D3  Ratings are per-group today (recompute-on-read from matches.group_id). Confirm
--       ratings stay scoped to (group, player) after players go global. (This migration
--       assumes YES — matches keep group_id; ratings recompute per group.)
--   D4  Approval model (see design-gap CONTRADICTIONS C1) is orthogonal but touches the
--       approvals table; not changed here.
--
-- TWO SHAPES ARE ON THE TABLE — the owner picks ONE:
--   SHAPE A (literal dispatch): players.id uuid PK = auth.users(id). Re-keys every FK
--           (match_players, tt_games, point_logs, approvals, matches.logger_player_id,
--           player_links) from int to uuid on live rows. Highest risk. Blocked by D2.
--   SHAPE B (lower-risk, RECOMMENDED for a live prod DB): keep players.id INT as an
--           internal surrogate, ADD players.auth_id uuid REFERENCES auth.users(id) as the
--           immutable identity, plus players.code. No FK re-keying. Enforces every Task-3
--           rule. Deviates from "players.id uuid PK" wording only in that the uuid is a
--           column, not the PK. Section 1 below is written for SHAPE B; Section 4 sketches
--           the extra steps SHAPE A additionally needs.
-- ---------------------------------------------------------------------------

BEGIN;

-- === Section 1 — ADDITIVE, SAFE (no data loss, no FK re-key) ================
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- 1a. players: immutable account id + permanent public code. game_name replaces the
--     globally-unique name; global uniqueness is DROPPED (see 1c).
ALTER TABLE players ADD COLUMN IF NOT EXISTS auth_id    uuid REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE players ADD COLUMN IF NOT EXISTS code       text;                -- 5-char public code, backfilled then NOT NULL + UNIQUE
ALTER TABLE players ADD COLUMN IF NOT EXISTS password_set boolean NOT NULL DEFAULT false;  -- true once a password is set (Task 6)
-- players.name (game name) and players.real_name already exist; created_at already exists.

-- 1b. Safe 5-char code generator: A-Z2-9 minus confusables O,0,I,1,L. 31 symbols, 31^5 ≈ 28.6M.
CREATE OR REPLACE FUNCTION rally_gen_player_code() RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  alphabet constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';  -- no O,0,I,1,L
  c text;
BEGIN
  LOOP
    c := '';
    FOR i IN 1..5 LOOP
      c := c || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    END LOOP;
    -- retry on the astronomically rare collision
    EXIT WHEN NOT EXISTS (SELECT 1 FROM players WHERE code = c);
  END LOOP;
  RETURN c;
END $$;

-- 1c. Names: DROP the global-unique constraint; enforce uniqueness WITHIN A GROUP only,
--     case-insensitively. Because game_name lives on the (global) player, "unique in a
--     group" is a co-membership rule, enforced with a trigger on group_members (1f), not
--     a plain index. First remove the old per-group index if it exists (it was keyed on
--     players.group_id, which SHAPE B keeps but SHAPE A drops).
DROP INDEX IF EXISTS ux_players_group_lower_name;   -- old global/per-group-int uniqueness

-- 1d. name_history: old names resolve after a rename.
CREATE TABLE IF NOT EXISTS name_history (
  player_id  integer NOT NULL REFERENCES players(id) ON DELETE CASCADE,   -- SHAPE A: uuid
  old_name   text    NOT NULL,
  changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_name_history_player ON name_history(player_id);

-- 1e. friendships: one row per unordered pair (enforce a_id < b_id). Accepted friendships
--     are the ONLY thing the court picker may read (rule enforced in API, not here).
CREATE TABLE IF NOT EXISTS friendships (
  a_id         integer NOT NULL REFERENCES players(id) ON DELETE CASCADE,  -- SHAPE A: uuid
  b_id         integer NOT NULL REFERENCES players(id) ON DELETE CASCADE,  -- SHAPE A: uuid
  status       text    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted')),
  requested_by integer NOT NULL REFERENCES players(id) ON DELETE CASCADE,  -- SHAPE A: uuid
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (a_id, b_id),
  CHECK (a_id < b_id)     -- canonical ordering => one row per pair
);

-- 1f. groups: add admin + boolean is_public + created_at. (Live groups.is_public is INT
--     today; keep it and ADD a boolean mirror, or convert — owner's call. Shown as a
--     converting ALTER; comment out if you prefer to keep the int.)
ALTER TABLE groups ADD COLUMN IF NOT EXISTS admin_id   integer REFERENCES players(id) ON DELETE SET NULL;  -- SHAPE A: uuid
ALTER TABLE groups ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
-- is_public: current column is integer 0/1. Leave as-is and treat !=0 as true, OR:
-- ALTER TABLE groups ALTER COLUMN is_public TYPE boolean USING (is_public <> 0);

-- 1g. group_members: replaces "a player row per group". Court picker + membership read this.
CREATE TABLE IF NOT EXISTS group_members (
  group_id  integer NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  player_id integer NOT NULL REFERENCES players(id) ON DELETE CASCADE,     -- SHAPE A: uuid
  joined_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, player_id)
);
-- per-group case-insensitive game-name uniqueness (co-membership rule):
CREATE UNIQUE INDEX IF NOT EXISTS ux_group_member_lower_name
  ON group_members (group_id, lower((SELECT name FROM players p WHERE p.id = group_members.player_id)));
--  NOTE: a subquery in an index expression is NOT allowed in Postgres — this uniqueness
--  MUST be a BEFORE INSERT/UPDATE trigger on group_members (and on players rename) instead.
--  Left here as intent; implement as trigger rally_check_group_name_unique(). (Flagged, not run.)

-- 1h. group_join_requests: private groups queue joins for the admin to approve.
CREATE TABLE IF NOT EXISTS group_join_requests (
  group_id   integer NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  player_id  integer NOT NULL REFERENCES players(id) ON DELETE CASCADE,    -- SHAPE A: uuid
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, player_id)
);

-- 1i. "deleting a group does NOT delete matches": matches.group_id must NOT cascade-delete.
--     Ensure the FK (if any) is ON DELETE SET NULL / RESTRICT, and add a nullable
--     matches.former_group_name tombstone so history survives a group deletion.
ALTER TABLE matches ADD COLUMN IF NOT EXISTS former_group_name text;
--   (Any FK matches.group_id -> groups(id) should be ON DELETE SET NULL; verify on live.)

-- === Section 2 — BACKFILL codes (safe; also see migrations/backfill_identity.py) ========
UPDATE players SET code = rally_gen_player_code() WHERE code IS NULL;
ALTER TABLE players ALTER COLUMN code SET NOT NULL;
ALTER TABLE players ADD CONSTRAINT ux_players_code UNIQUE (code);

-- backfill auth_id for LINKED players (auth_sub IS the Supabase auth.users uuid):
UPDATE players p
   SET auth_id = pl.auth_sub::uuid
  FROM player_links pl
 WHERE pl.player_id = p.id
   AND p.auth_id IS NULL;
--   UNLINKED players keep auth_id NULL until DECISION D2 is resolved.

-- === Section 3 — DATA MIGRATION to the global model (GATED on D1–D2) ====================
--   Runs ONLY under SHAPE A, and ONLY after D1/D2 are decided. Sketch, deliberately not
--   executable as-is:
--     * pick each auth user's surviving game_name (D1) -> insert losers into name_history;
--     * create ONE global player (id = auth uuid) per auth user;
--     * INSERT group_members from the old per-group player rows;
--     * remap match_players.player_id, tt_games.{server,receiver,winner}_player_id,
--       point_logs.server_player_id, approvals.player_id, matches.logger_player_id
--       from old int id -> the user's uuid, via player_links;
--     * handle unlinked players per D2;
--     * only then drop players.group_id and the old integer id path.
--   This is where the collision/row-count verification from Task 5 must be asserted BEFORE
--   COMMIT. Left as a documented sketch on purpose — do not run without the decisions.

-- === Section 4 — extra steps SHAPE A needs (FK re-key) — NOT for SHAPE B =================
--   Changing players PK int->uuid requires: add players.uuid, backfill, drop each FK,
--   add uuid FK columns, backfill them from the int mapping, swap PKs, drop int columns.
--   High risk on live data; do on a branch first. Omitted here pending SHAPE choice.

-- Verify before committing (examples):
--   SELECT count(*) FROM players WHERE code IS NULL;              -- expect 0
--   SELECT count(*) - count(DISTINCT code) FROM players;          -- expect 0 (no code collisions)
--   SELECT count(*) FROM players WHERE auth_id IS NULL;           -- = number of unlinked players (D2)

COMMIT;
-- ROLLBACK; -- use if any verification above is unexpected.
