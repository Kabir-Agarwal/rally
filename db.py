"""Data layer for Rally — CLEAN FOUNDATION (2026-07-27, Option C).

Identity is GLOBAL: a player row's id IS the auth user id (auth.users.id uuid). No per-group
player rows, no player_links, no integer ids. Groups are optional; a match may have group_id NULL.

Schema is OWNED BY THE MIGRATIONS on live Postgres (rally_clean_foundation). This module does NOT
auto-migrate — if a required column is missing it FAILS LOUDLY at startup (see require_schema()).
The SQLite path mirrors the live schema for local dev + tests; uuids and player codes are generated
in PYTHON (not gen_random_uuid()/rally_new_code()), so one query path serves both backends.
"""
from __future__ import annotations
import os
import uuid
import sqlite3
import secrets
from datetime import datetime
from pathlib import Path

import ratings

DB_PATH = Path(__file__).parent / "tennis.db"
# Player/group code alphabet: A-Z 2-9 minus confusables O, 0, I, 1, L  (matches DB rally_new_code).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

DATABASE_URL = os.environ.get("DATABASE_URL") or ""


def _is_pg():
    return DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql")


# Mirrors the live Postgres schema (rally_clean_foundation). SQLite types: uuid->TEXT, bool->INTEGER,
# timestamptz->TEXT. CHECK constraints match. Per-group game-name uniqueness is a live PG trigger
# (trg_group_name_unique); on SQLite it is enforced in app code (see group_name_taken()).
SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
  id TEXT PRIMARY KEY,                 -- = auth.users.id (uuid)
  code TEXT UNIQUE NOT NULL,           -- permanent public player code (Name#CODE)
  game_name TEXT NOT NULL,
  real_name TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT UNIQUE NOT NULL,
  is_public INTEGER NOT NULL DEFAULT 1,
  admin_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS group_members (
  group_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  joined_at TEXT NOT NULL,
  PRIMARY KEY (group_id, player_id)
);
CREATE TABLE IF NOT EXISTS group_join_requests (
  group_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (group_id, player_id)
);
CREATE TABLE IF NOT EXISTS matches (
  id TEXT PRIMARY KEY,
  group_id TEXT,                       -- NULLABLE: a match need not belong to a group
  former_group_name TEXT,              -- kept if the group is later deleted
  kind TEXT NOT NULL CHECK (kind IN ('singles','doubles','tt')),
  status TEXT NOT NULL DEFAULT 'live'
    CHECK (status IN ('live','frozen','pending_approval','counted','disputed','deleted')),
  logger_id TEXT,
  created_at TEXT, started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS match_players (
  match_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  side INTEGER NOT NULL,
  rotation_pos INTEGER,
  PRIMARY KEY (match_id, player_id)
);
CREATE TABLE IF NOT EXISTS match_sets (
  match_id TEXT NOT NULL,
  set_no INTEGER NOT NULL,
  games_side1 INTEGER NOT NULL DEFAULT 0,
  games_side2 INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (match_id, set_no)
);
CREATE TABLE IF NOT EXISTS point_logs (
  match_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  winner_side INTEGER NOT NULL,
  server_player_id TEXT,
  point_winner_player_id TEXT,
  PRIMARY KEY (match_id, seq)
);
CREATE TABLE IF NOT EXISTS tt_games (
  match_id TEXT NOT NULL,
  game_no INTEGER NOT NULL,
  round_no INTEGER,
  server_player_id TEXT,
  receiver_player_id TEXT,
  winner_player_id TEXT,
  PRIMARY KEY (match_id, game_no)
);
CREATE TABLE IF NOT EXISTS friendships (
  a_id TEXT NOT NULL,
  b_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted')),
  requested_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (a_id, b_id)
);
CREATE TABLE IF NOT EXISTS name_history (
  player_id TEXT NOT NULL,
  old_name TEXT NOT NULL,
  changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  match_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('approve','dispute')),
  reason TEXT,
  approved_at TEXT,
  PRIMARY KEY (match_id, player_id)
);
CREATE TABLE IF NOT EXISTS freeze_requests (
  match_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('freeze','resume')),
  approved_at TEXT,
  PRIMARY KEY (match_id, player_id, kind)
);
CREATE TABLE IF NOT EXISTS admin_log (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT
);
"""

REQUIRED = {  # column presence the app depends on — checked loudly at startup (no silent patching)
    "players": ("id", "code", "game_name", "real_name", "created_at"),
    "matches": ("id", "group_id", "former_group_name", "kind", "status", "logger_id"),
    "match_players": ("match_id", "player_id", "side", "rotation_pos"),
    "groups": ("id", "name", "code", "is_public", "admin_id"),
    "friendships": ("a_id", "b_id", "status", "requested_by"),
    "approvals": ("match_id", "player_id", "action"),
}


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def gen_uuid():
    return str(uuid.uuid4())


# --- Postgres shim: present the sqlite3.Row / cursor interface the code expects ------
class _Row(dict):
    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._vals = list(values)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._vals[k]
        return super().__getitem__(k)


def _qmark(sql):
    return sql.replace("?", "%s")


class _PGCursor:
    def __init__(self, cur):
        self.c = cur

    def fetchone(self):
        row = self.c.fetchone()
        return None if row is None else _Row([d[0] for d in self.c.description], row)

    def fetchall(self):
        names = [d[0] for d in self.c.description]
        return [_Row(names, r) for r in self.c.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class _PGConn:
    row_factory = None

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(_qmark(sql), tuple(params))
        return _PGCursor(cur)

    def executescript(self, sql):
        cur = self.raw.cursor()
        cur.execute(sql)
        self.raw.commit()

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from sqlalchemy import create_engine
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        _ENGINE = create_engine(url, pool_pre_ping=True)
    return _ENGINE


def connect(path=DB_PATH):
    if _is_pg():
        return _PGConn(_engine().raw_connection())
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=OFF")   # match the live model (group_id null on group delete, etc.)
    return con


def require_schema(con):
    """FAIL LOUDLY if a required column is missing. The schema is owned by the migrations; the app
    must never silently self-patch (that is how columns went missing before)."""
    for table, cols in REQUIRED.items():
        try:
            con.execute(f"SELECT {', '.join(cols)} FROM {table} LIMIT 0").fetchall()
        except Exception as e:
            raise RuntimeError(
                f"schema check failed for {table}({', '.join(cols)}): {e}. "
                f"The database is not migrated to rally_clean_foundation. Refusing to start."
            )


def init_db(path=DB_PATH):
    if _is_pg():
        con = connect(path)
        require_schema(con)     # live PG is already migrated; verify, never create/patch
        con.close()
        return
    con = connect(path)
    con.executescript(SCHEMA)   # SQLite dev/test: build the mirror
    con.commit()
    require_schema(con)
    con.close()


try:
    import psycopg
    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.errors.IntegrityError)
except Exception:
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


# --- codes ----------------------------------------------------------------
def _unique_code(con, table, length):
    for _ in range(50):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))
        if not con.execute(f"SELECT 1 FROM {table} WHERE code=?", (code,)).fetchone():
            return code
    raise RuntimeError(f"could not allocate a unique {table} code")


def new_player_code(con):
    return _unique_code(con, "players", 5)


def new_group_code(con):
    return _unique_code(con, "groups", 6)


# --- players (global identity) --------------------------------------------
def get_player(con, pid):
    return con.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()


def get_player_by_code(con, code):
    return con.execute("SELECT * FROM players WHERE code=?", (code.strip().upper(),)).fetchone()


def create_player(con, pid, game_name, real_name=None):
    """First sign-in: the auth user id becomes the player id. Generates a permanent code."""
    game_name = (game_name or "").strip()
    if not game_name:
        raise ValueError("game name required")
    code = new_player_code(con)
    con.execute(
        "INSERT INTO players(id, code, game_name, real_name, created_at) VALUES(?,?,?,?,?)",
        (pid, code, game_name, (real_name or "").strip() or None, now()),
    )
    con.commit()
    return code


def rename_player(con, pid, game_name=None, real_name=None):
    if game_name is not None:
        game_name = game_name.strip()
        if not game_name:
            raise ValueError("game name required")
        cur = get_player(con, pid)
        if cur and cur["game_name"] and cur["game_name"] != game_name:
            con.execute("INSERT INTO name_history(player_id, old_name, changed_at) VALUES(?,?,?)",
                        (pid, cur["game_name"], now()))
        con.execute("UPDATE players SET game_name=? WHERE id=?", (game_name, pid))
    if real_name is not None:
        con.execute("UPDATE players SET real_name=? WHERE id=?", ((real_name.strip() or None), pid))
    con.commit()


# --- groups ---------------------------------------------------------------
def create_group(con, name, admin_id):
    gid, code = gen_uuid(), new_group_code(con)
    con.execute("INSERT INTO groups(id, name, code, is_public, admin_id, created_at) VALUES(?,?,?,?,?,?)",
                (gid, name.strip(), code, 1, admin_id, now()))
    con.execute("INSERT INTO group_members(group_id, player_id, joined_at) VALUES(?,?,?)",
                (gid, admin_id, now()))
    con.commit()
    return gid, code


def group_by_code(con, code):
    return con.execute("SELECT * FROM groups WHERE code=?", (code.strip().upper(),)).fetchone()


def group_by_id(con, gid):
    return con.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()


def groups_of_player(con, pid):
    return con.execute(
        "SELECT g.* FROM groups g JOIN group_members gm ON gm.group_id=g.id "
        "WHERE gm.player_id=? ORDER BY g.created_at DESC", (pid,)).fetchall()


def is_member(con, gid, pid):
    return bool(con.execute("SELECT 1 FROM group_members WHERE group_id=? AND player_id=?",
                            (gid, pid)).fetchone())


def add_member(con, gid, pid):
    if not is_member(con, gid, pid):
        con.execute("INSERT INTO group_members(group_id, player_id, joined_at) VALUES(?,?,?)",
                    (gid, pid, now()))
        con.commit()


def remove_member(con, gid, pid):
    con.execute("DELETE FROM group_members WHERE group_id=? AND player_id=?", (gid, pid))
    con.commit()


def members_of(con, gid):
    return con.execute(
        "SELECT p.* FROM players p JOIN group_members gm ON gm.player_id=p.id "
        "WHERE gm.group_id=? ORDER BY LOWER(p.game_name)", (gid,)).fetchall()


def group_name_taken(con, gid, game_name, exclude_pid=None):
    """Per-group game-name uniqueness (the live PG trigger; enforced here for SQLite/app writes)."""
    rows = con.execute(
        "SELECT p.id FROM players p JOIN group_members gm ON gm.player_id=p.id "
        "WHERE gm.group_id=? AND LOWER(p.game_name)=LOWER(?)", (gid, game_name)).fetchall()
    return any((r["id"] != exclude_pid) for r in rows)


def add_join_request(con, gid, pid):
    con.execute("INSERT OR IGNORE INTO group_join_requests(group_id, player_id, created_at) VALUES(?,?,?)",
                (gid, pid, now())) if not _is_pg() else con.execute(
        "INSERT INTO group_join_requests(group_id, player_id, created_at) VALUES(?,?,?) "
        "ON CONFLICT DO NOTHING", (gid, pid, now()))
    con.commit()


def join_requests_of(con, gid):
    return con.execute(
        "SELECT p.* FROM players p JOIN group_join_requests r ON r.player_id=p.id "
        "WHERE r.group_id=? ORDER BY r.created_at", (gid,)).fetchall()


def clear_join_request(con, gid, pid):
    con.execute("DELETE FROM group_join_requests WHERE group_id=? AND player_id=?", (gid, pid))
    con.commit()


def set_public(con, gid, is_public):
    con.execute("UPDATE groups SET is_public=? WHERE id=?", (1 if is_public else 0, gid))
    con.commit()


def rename_group(con, gid, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    con.execute("UPDATE groups SET name=? WHERE id=?", (name, gid))
    con.commit()


def regen_group_code(con, gid):
    code = new_group_code(con)
    con.execute("UPDATE groups SET code=? WHERE id=?", (code, gid))
    con.commit()
    return code


def set_admin(con, gid, pid):
    con.execute("UPDATE groups SET admin_id=? WHERE id=?", (pid, gid))
    con.commit()


def delete_group(con, gid):
    """Delete a group but KEEP its matches: group_id -> NULL, stamped with former_group_name."""
    g = group_by_id(con, gid)
    former = g["name"] if g else None
    con.execute("UPDATE matches SET group_id=NULL, former_group_name=? WHERE group_id=?", (former, gid))
    con.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
    con.execute("DELETE FROM group_join_requests WHERE group_id=?", (gid,))
    con.execute("DELETE FROM groups WHERE id=?", (gid,))
    con.commit()


# --- friendships (one row per unordered pair; a_id<b_id) ------------------
def _pair(x, y):
    return (x, y) if x < y else (y, x)


def friendship(con, x, y):
    a, b = _pair(x, y)
    return con.execute("SELECT * FROM friendships WHERE a_id=? AND b_id=?", (a, b)).fetchone()


def request_friend(con, requester, other):
    if requester == other:
        raise ValueError("cannot friend yourself")
    a, b = _pair(requester, other)
    existing = friendship(con, a, b)
    if existing:
        if existing["status"] == "accepted":
            return "accepted"
        # a pending request from the OTHER side -> accept it
        if existing["requested_by"] != requester:
            con.execute("UPDATE friendships SET status='accepted' WHERE a_id=? AND b_id=?", (a, b))
            con.commit()
            return "accepted"
        return "pending"
    con.execute("INSERT INTO friendships(a_id, b_id, status, requested_by, created_at) VALUES(?,?, 'pending', ?, ?)",
                (a, b, requester, now()))
    con.commit()
    return "pending"


def accept_friend(con, me, other):
    a, b = _pair(me, other)
    con.execute("UPDATE friendships SET status='accepted' WHERE a_id=? AND b_id=? AND requested_by<>?",
                (a, b, me))
    con.commit()


def decline_friend(con, me, other):
    a, b = _pair(me, other)
    con.execute("DELETE FROM friendships WHERE a_id=? AND b_id=?", (a, b))
    con.commit()


def accepted_friends(con, pid):
    rows = con.execute(
        "SELECT p.* FROM players p JOIN friendships f "
        "ON (f.a_id=p.id OR f.b_id=p.id) "
        "WHERE f.status='accepted' AND (f.a_id=? OR f.b_id=?) AND p.id<>? "
        "ORDER BY LOWER(p.game_name)", (pid, pid, pid)).fetchall()
    return rows


def pending_friend_requests(con, pid):
    """Incoming pending requests (someone else asked me)."""
    return con.execute(
        "SELECT p.* FROM players p JOIN friendships f ON (f.a_id=p.id OR f.b_id=p.id) "
        "WHERE f.status='pending' AND f.requested_by=p.id AND (f.a_id=? OR f.b_id=?) AND p.id<>?",
        (pid, pid, pid)).fetchall()


def search_players(con, q):
    q = (q or "").strip()
    if not q:
        return []
    like = f"%{q.lower()}%"
    return con.execute(
        "SELECT * FROM players WHERE LOWER(game_name) LIKE ? OR UPPER(code)=? ORDER BY LOWER(game_name) LIMIT 20",
        (like, q.upper())).fetchall()


# --- matches --------------------------------------------------------------
def match_row(con, mid):
    return con.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()


def match_players(con, mid):
    return con.execute(
        "SELECT mp.*, p.game_name AS name, p.real_name FROM match_players mp "
        "JOIN players p ON p.id=mp.player_id WHERE mp.match_id=? "
        "ORDER BY mp.side, mp.rotation_pos, mp.player_id", (mid,)).fetchall()


def match_sets(con, mid):
    return con.execute("SELECT * FROM match_sets WHERE match_id=? ORDER BY set_no", (mid,)).fetchall()


def tt_games(con, mid):
    return con.execute("SELECT * FROM tt_games WHERE match_id=? ORDER BY game_no", (mid,)).fetchall()


def sides(con, mid):
    rows = match_players(con, mid)
    s1 = [r["player_id"] for r in rows if r["side"] == 1]
    s2 = [r["player_id"] for r in rows if r["side"] == 2]
    rot = [r["player_id"] for r in sorted(
        [r for r in rows if r["rotation_pos"]], key=lambda r: r["rotation_pos"])]
    return s1, s2, rot


def participants(con, mid):
    return [r["player_id"] for r in con.execute(
        "SELECT player_id FROM match_players WHERE match_id=?", (mid,)).fetchall()]


def set_status(con, mid, status):
    con.execute("UPDATE matches SET status=? WHERE id=?", (status, mid))
    con.commit()


# --- rating rebuild (GLOBAL; optional group filter) -----------------------
# A match counts toward ratings only when status='counted'. Ratings are global per player,
# rebuilt from all counted matches (optionally restricted to one group).
def _match_to_dict(con, m):
    mid = m["id"]
    s1, s2, rot = sides(con, mid)
    if m["kind"] == "tt":
        games = [g["winner_player_id"] for g in tt_games(con, mid)]
        return {"kind": "tt", "rotation": rot, "games": games}
    sets = [(s["games_side1"], s["games_side2"]) for s in match_sets(con, mid)]
    d = {"kind": m["kind"], "side1": s1, "side2": s2, "sets": sets}
    pts = con.execute(
        "SELECT winner_side, COUNT(*) c FROM point_logs WHERE match_id=? GROUP BY winner_side", (mid,)
    ).fetchall()
    if pts:
        by = {r["winner_side"]: r["c"] for r in pts}
        d["points"] = (by.get(1, 0), by.get(2, 0))
    return d


def rating_state(con, group_id=None):
    """Global rating state from counted matches. Pass group_id to restrict to one group."""
    if group_id:
        ms = con.execute(
            "SELECT * FROM matches WHERE status='counted' AND group_id=? "
            "ORDER BY COALESCE(finished_at, created_at), id", (group_id,)).fetchall()
    else:
        ms = con.execute(
            "SELECT * FROM matches WHERE status='counted' "
            "ORDER BY COALESCE(finished_at, created_at), id").fetchall()
    return ratings.rebuild([_match_to_dict(con, m) for m in ms])


# --- admin log ------------------------------------------------------------
def log_admin(con, action, target=""):
    con.execute("INSERT INTO admin_log(at, action, target) VALUES(?,?,?)", (now(), action, target))
    con.commit()


if __name__ == "__main__":
    con = connect(":memory:")
    con.executescript(SCHEMA)
    require_schema(con)
    # identity: create two global players
    pa, pb = gen_uuid(), gen_uuid()
    ca = create_player(con, pa, "Ann")
    cb = create_player(con, pb, "Bob")
    assert ca != cb and len(ca) == 5 and all(ch in CODE_ALPHABET for ch in ca)
    # a match with NO group scores fine
    import logic
    mid = logic.start_match(con, None, "singles", [pa], [pb], [], pa)
    assert match_row(con, mid)["group_id"] is None
    logic.edit_sets(con, mid, [(6, 4)])
    logic.finish_match(con, mid)                     # -> pending_approval (needs approvals)
    logic.approve(con, mid, pa); logic.approve(con, mid, pb)
    assert match_row(con, mid)["status"] == "counted"
    st = rating_state(con)
    assert st["singles"][pa] > 1200 and st["singles"][pb] < 1200
    # friendship
    assert request_friend(con, pa, pb) == "pending"
    assert request_friend(con, pb, pa) == "accepted"      # reciprocal accepts
    assert [p["id"] for p in accepted_friends(con, pa)] == [pb]
    print("OK db")
