"""SQLite schema + helpers for tennis-scores.

Ratings are recomputed from finished matches on read (see ratings.rebuild).
# ponytail: no rating_cache/pair_ratings tables — friend-group history is tiny, so a
# full rebuild per read is trivial and cannot go stale. Add cached tables only if a
# group's match count ever makes per-request rebuild measurably slow.
"""
from __future__ import annotations
import os
import sqlite3
import secrets
import string
from datetime import datetime, timedelta
from pathlib import Path

import ratings

DB_PATH = Path(__file__).parent / "tennis.db"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # A-Z2-9, no ambiguous 0/O/1/I
APPROVAL_HOURS = 24
RATING_STATUSES = ("finished", "delete_requested")  # both count toward ratings

# Production-safe backend: DATABASE_URL (Postgres) if set, else the local SQLite file.
# The SQLite path is byte-for-byte the original — local dev + all tests are unchanged.
DATABASE_URL = os.environ.get("DATABASE_URL") or ""


def _is_pg():
    return DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql")

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT UNIQUE NOT NULL,
  is_public INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  -- SQLite-dev-only: COLLATE NOCASE is not valid on Postgres. This whole SCHEMA string
  -- runs ONLY on the SQLite path (executescript). Postgres uses schema.py, where the same
  -- case-insensitive uniqueness is a functional unique index on LOWER(name). Keep in sync.
  UNIQUE(group_id, name COLLATE NOCASE)
);
CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL,
  played_on TEXT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  logger_player_id INTEGER,
  created_at TEXT, started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS match_players (
  match_id INTEGER NOT NULL,
  player_id INTEGER NOT NULL,
  side INTEGER NOT NULL,
  rotation_pos INTEGER
);
CREATE TABLE IF NOT EXISTS match_sets (
  match_id INTEGER NOT NULL,
  set_no INTEGER NOT NULL,
  games_side1 INTEGER NOT NULL DEFAULT 0,
  games_side2 INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tt_games (
  match_id INTEGER NOT NULL,
  game_no INTEGER NOT NULL,
  server_player_id INTEGER,
  winner_player_id INTEGER
);
CREATE TABLE IF NOT EXISTS point_logs (
  match_id INTEGER NOT NULL,
  seq INTEGER NOT NULL,
  winner_side INTEGER NOT NULL,
  server_player_id INTEGER
);
CREATE TABLE IF NOT EXISTS approvals (
  match_id INTEGER NOT NULL,
  player_id INTEGER NOT NULL,
  action TEXT NOT NULL,
  approved_at TEXT,
  deadline TEXT
);
CREATE TABLE IF NOT EXISTS admin_log (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT
);
"""


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def deadline_24h():
    return (datetime.utcnow() + timedelta(hours=APPROVAL_HOURS)).isoformat(timespec="seconds")


# --- Postgres shim: present the sqlite3.Row / cursor interface the code expects ------
# ponytail: a ~40-line DBAPI adapter (qmark->pyformat, dict+positional rows, lastval()
# for lastrowid) instead of rewriting ~60 raw queries into SQLAlchemy Core. The SQLite
# path stays untouched; the schema is shared via schema.py (used for create_all + tests).
class _Row(dict):
    """dict row that also supports positional indexing, so both r["c"] and r[0] work."""
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
        if row is None:
            return None
        return _Row([d[0] for d in self.c.description], row)

    def fetchall(self):
        names = [d[0] for d in self.c.description]
        return [_Row(names, r) for r in self.c.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        self.c.execute("SELECT lastval()")
        return self.c.fetchone()[0]


class _PGConn:
    """Thin wrapper over a psycopg DBAPI connection matching sqlite3.Connection usage."""
    row_factory = None  # settable no-op; PG rows already behave like sqlite3.Row

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(_qmark(sql), tuple(params))
        return _PGCursor(cur)

    def executescript(self, sql):  # only exercised on the SQLite path in practice
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
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(path=DB_PATH):
    if _is_pg():
        import schema
        schema.metadata.create_all(_engine())
        return
    con = connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


# Duplicate-name detection works across backends (sqlite + psycopg raise different types).
try:
    import psycopg
    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.errors.IntegrityError)
except Exception:  # psycopg only needed for the Postgres backend
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


# --- groups ---------------------------------------------------------------
def gen_code(con):
    for _ in range(50):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not con.execute("SELECT 1 FROM groups WHERE code=?", (code,)).fetchone():
            return code
    raise RuntimeError("could not allocate a unique group code")


def create_group(con, name):
    code = gen_code(con)
    cur = con.execute(
        "INSERT INTO groups(name, code, is_public, created_at) VALUES(?,?,0,?)",
        (name.strip(), code, now()),
    )
    con.commit()
    return cur.lastrowid, code


def group_by_code(con, code):
    return con.execute("SELECT * FROM groups WHERE code=?", (code.upper().strip(),)).fetchone()


def group_by_id(con, gid):
    return con.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()


def set_public(con, gid, is_public):
    con.execute("UPDATE groups SET is_public=? WHERE id=?", (1 if is_public else 0, gid))
    con.commit()


def all_groups(con):
    return con.execute("SELECT * FROM groups ORDER BY created_at DESC, id DESC").fetchall()


def regen_code(con, gid):
    """Assign a fresh unique code; the old code stops resolving immediately."""
    code = gen_code(con)
    con.execute("UPDATE groups SET code=? WHERE id=?", (code, gid))
    con.commit()
    return code


def rename_group(con, gid, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    con.execute("UPDATE groups SET name=? WHERE id=?", (name, gid))
    con.commit()


def _match_ids_of_group(con, gid):
    return [r["id"] for r in con.execute("SELECT id FROM matches WHERE group_id=?", (gid,)).fetchall()]


def _match_ids_of_player(con, pid):
    return [r["match_id"] for r in
            con.execute("SELECT DISTINCT match_id FROM match_players WHERE player_id=?", (pid,)).fetchall()]


def _delete_matches(con, mids):
    for mid in mids:
        for t in ("match_players", "match_sets", "tt_games", "point_logs", "approvals"):
            con.execute(f"DELETE FROM {t} WHERE match_id=?", (mid,))
        con.execute("DELETE FROM matches WHERE id=?", (mid,))


def delete_group(con, gid):
    """Cascade-delete a group and ONLY its own data."""
    _delete_matches(con, _match_ids_of_group(con, gid))
    con.execute("DELETE FROM players WHERE group_id=?", (gid,))
    con.execute("DELETE FROM groups WHERE id=?", (gid,))
    con.commit()


def rename_player(con, pid, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    try:
        con.execute("UPDATE players SET name=? WHERE id=?", (name, pid))
        con.commit()
    except INTEGRITY_ERRORS:
        raise ValueError("duplicate name in this group")


def delete_player(con, pid):
    """Delete a player and cascade the matches they played (their group only)."""
    _delete_matches(con, _match_ids_of_player(con, pid))
    con.execute("DELETE FROM players WHERE id=?", (pid,))
    con.commit()


def player_row(con, pid):
    return con.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()


# --- admin log ------------------------------------------------------------
def log_admin(con, action, target=""):
    con.execute("INSERT INTO admin_log(at, action, target) VALUES(?,?,?)", (now(), action, target))
    con.commit()


def admin_logs(con, limit=100):
    return con.execute("SELECT * FROM admin_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


# --- players --------------------------------------------------------------
def add_player(con, group_id, name):
    name = name.strip()
    if not name:
        raise ValueError("name required")
    try:
        cur = con.execute(
            "INSERT INTO players(group_id, name, created_at) VALUES(?,?,?)",
            (group_id, name, now()),
        )
        con.commit()
        return cur.lastrowid
    except INTEGRITY_ERRORS:
        raise ValueError("duplicate name in this group")


def players_of(con, group_id):
    return con.execute(
        "SELECT * FROM players WHERE group_id=? ORDER BY LOWER(name)", (group_id,)
    ).fetchall()


# --- matches --------------------------------------------------------------
def match_row(con, mid):
    return con.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()


def match_players(con, mid):
    return con.execute(
        "SELECT mp.*, p.name FROM match_players mp JOIN players p ON p.id=mp.player_id "
        "WHERE mp.match_id=? ORDER BY mp.side, mp.rotation_pos, mp.player_id",
        (mid,),
    ).fetchall()


def match_sets(con, mid):
    return con.execute(
        "SELECT * FROM match_sets WHERE match_id=? ORDER BY set_no", (mid,)
    ).fetchall()


def tt_games(con, mid):
    return con.execute(
        "SELECT * FROM tt_games WHERE match_id=? ORDER BY game_no", (mid,)
    ).fetchall()


def sides(con, mid):
    """Return (side1_ids, side2_ids, rotation_ids)."""
    rows = match_players(con, mid)
    s1 = [r["player_id"] for r in rows if r["side"] == 1]
    s2 = [r["player_id"] for r in rows if r["side"] == 2]
    rot = [r["player_id"] for r in sorted(
        [r for r in rows if r["rotation_pos"]], key=lambda r: r["rotation_pos"])]
    return s1, s2, rot


# --- rating rebuild -------------------------------------------------------
def _match_to_dict(con, m):
    mid = m["id"]
    s1, s2, rot = sides(con, mid)
    if m["kind"] == "tt":
        games = [g["winner_player_id"] for g in tt_games(con, mid)]
        return {"kind": "tt", "rotation": rot, "games": games}
    sets = [(s["games_side1"], s["games_side2"]) for s in match_sets(con, mid)]
    d = {"kind": m["kind"], "side1": s1, "side2": s2, "sets": sets}
    # live-scored matches carry point totals -> point-dominance factor (typed matches don't)
    pts = con.execute(
        "SELECT winner_side, COUNT(*) c FROM point_logs WHERE match_id=? GROUP BY winner_side", (mid,)
    ).fetchall()
    if pts:
        by = {r["winner_side"]: r["c"] for r in pts}
        d["points"] = (by.get(1, 0), by.get(2, 0))
    return d


def rating_state(con, group_id):
    """Rebuild rating state for a group from rating-eligible matches in finish order."""
    ms = con.execute(
        "SELECT * FROM matches WHERE group_id=? AND status IN (?,?) "
        "ORDER BY COALESCE(finished_at, created_at), id",
        (group_id, *RATING_STATUSES),
    ).fetchall()
    return ratings.rebuild([_match_to_dict(con, m) for m in ms])


if __name__ == "__main__":
    # self-check: schema builds, code is unique & legal, isolation holds
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    g1, c1 = create_group(con, "Alpha")
    g2, c2 = create_group(con, "Beta")
    assert c1 != c2 and len(c1) == 6 and all(ch in CODE_ALPHABET for ch in c1)
    p1 = add_player(con, g1, "Sam")
    try:
        add_player(con, g1, "sam")  # ci duplicate
        assert False, "should reject dup"
    except ValueError:
        pass
    p2 = add_player(con, g2, "Sam")  # same name, different group = fine
    assert p1 != p2
    print("OK db")
