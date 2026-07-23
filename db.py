"""SQLite schema + helpers for tennis-scores.

Ratings are recomputed from finished matches on read (see ratings.rebuild).
# ponytail: no rating_cache/pair_ratings tables — friend-group history is tiny, so a
# full rebuild per read is trivial and cannot go stale. Add cached tables only if a
# group's match count ever makes per-request rebuild measurably slow.
"""
from __future__ import annotations
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
"""


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def deadline_24h():
    return (datetime.utcnow() + timedelta(hours=APPROVAL_HOURS)).isoformat(timespec="seconds")


def connect(path=DB_PATH):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(path=DB_PATH):
    con = connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


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
    except sqlite3.IntegrityError:
        raise ValueError("duplicate name in this group")


def players_of(con, group_id):
    return con.execute(
        "SELECT * FROM players WHERE group_id=? ORDER BY name COLLATE NOCASE", (group_id,)
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
    return {"kind": m["kind"], "side1": s1, "side2": s2, "sets": sets}


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
