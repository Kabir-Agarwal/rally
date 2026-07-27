"""Match lifecycle — CLEAN FOUNDATION. Status flow:
   live -> (finish) -> pending_approval -> (every participant approves) -> counted
   counted -> (any participant un-approves) -> pending_approval   (ratings roll back automatically,
              because db.rating_state only reads status='counted')
   pending_approval/counted -> (any participant disputes) -> disputed
   live -> frozen (every participant requests freeze) -> live (every participant requests resume)
   any -> deleted (soft)
Ratings are recomputed from counted matches on read, so no cache to invalidate.
"""
from __future__ import annotations
import db
from db import now, gen_uuid


# --- validation -----------------------------------------------------------
def legal_set(a, b):
    hi, lo = max(a, b), min(a, b)
    return (hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6))


def validate_sets(sets):
    clean = [(a, b) for a, b in sets if not (a == 0 and b == 0)]
    if not clean:
        raise ValueError("no sets played")
    if len(clean) > 5:
        raise ValueError("max 5 sets")
    for a, b in clean:
        if not legal_set(a, b):
            raise ValueError(f"illegal set {a}-{b}")
    return clean


# --- start (one live match per player, global) ----------------------------
def _pname(con, pid):
    r = db.get_player(con, pid)
    return r["game_name"] if r else "?"


def _live_match_of(con, pid):
    row = con.execute(
        "SELECT m.id FROM matches m JOIN match_players mp ON mp.match_id=m.id "
        "WHERE m.status='live' AND mp.player_id=? LIMIT 1", (pid,)).fetchone()
    return row["id"] if row else None


def start_match(con, group_id, kind, side1, side2, rotation, logger_id,
                played_on=None, enforce_live=True):
    ids = list(rotation) if kind == "tt" else list(side1) + list(side2)
    if enforce_live:
        for pid in ids:
            if _live_match_of(con, pid):
                raise ValueError(f"{_pname(con, pid)} is already in a live match — finish it first.")
    mid, ts = gen_uuid(), now()
    con.execute(
        "INSERT INTO matches(id, group_id, kind, status, logger_id, created_at, started_at) "
        "VALUES(?,?,?, 'live', ?, ?, ?)", (mid, group_id, kind, logger_id, ts, ts))
    if kind == "tt":
        for pos, pid in enumerate(rotation, start=1):
            con.execute("INSERT INTO match_players(match_id, player_id, side, rotation_pos) VALUES(?,?,0,?)",
                        (mid, pid, pos))
    else:
        for pid in side1:
            con.execute("INSERT INTO match_players(match_id, player_id, side) VALUES(?,?,1)", (mid, pid))
        for pid in side2:
            con.execute("INSERT INTO match_players(match_id, player_id, side) VALUES(?,?,2)", (mid, pid))
    con.commit()
    return mid


def save_played(con, group_id, kind, side1, side2, rotation, sets, logger_id, played_on=None):
    mid = start_match(con, group_id, kind, side1, side2, rotation, logger_id, played_on, enforce_live=False)
    if kind != "tt":
        _write_sets(con, mid, sets)
    finish_match(con, mid)
    return mid


# --- scoring edits --------------------------------------------------------
def _write_sets(con, mid, sets):
    con.execute("DELETE FROM match_sets WHERE match_id=?", (mid,))
    for i, (a, b) in enumerate(sets, start=1):
        con.execute("INSERT INTO match_sets(match_id, set_no, games_side1, games_side2) VALUES(?,?,?,?)",
                    (mid, i, int(a), int(b)))
    con.commit()


def edit_sets(con, mid, sets):
    m = db.match_row(con, mid)
    if m["status"] not in ("live", "pending_approval", "counted"):
        raise ValueError("match is not editable")
    _write_sets(con, mid, sets)


def log_point(con, mid, winner_side, server_player_id, point_winner_player_id=None):
    seq = con.execute("SELECT COALESCE(MAX(seq),0)+1 FROM point_logs WHERE match_id=?", (mid,)).fetchone()[0]
    con.execute(
        "INSERT INTO point_logs(match_id, seq, winner_side, server_player_id, point_winner_player_id) "
        "VALUES(?,?,?,?,?)", (mid, seq, winner_side, server_player_id, point_winner_player_id))
    con.commit()


def undo_point(con, mid):
    row = con.execute("SELECT MAX(seq) s FROM point_logs WHERE match_id=?", (mid,)).fetchone()
    if row and row["s"]:
        con.execute("DELETE FROM point_logs WHERE match_id=? AND seq=?", (mid, row["s"]))
        con.commit()


def log_tt_game(con, mid, server_player_id, winner_player_id, receiver_player_id=None):
    g = con.execute("SELECT COALESCE(MAX(game_no),0)+1 FROM tt_games WHERE match_id=?", (mid,)).fetchone()[0]
    con.execute(
        "INSERT INTO tt_games(match_id, game_no, round_no, server_player_id, receiver_player_id, winner_player_id) "
        "VALUES(?,?,?,?,?,?)", (mid, g, g, server_player_id, receiver_player_id, winner_player_id))
    con.commit()


def undo_tt_game(con, mid):
    row = con.execute("SELECT MAX(game_no) g FROM tt_games WHERE match_id=?", (mid,)).fetchone()
    if row and row["g"]:
        con.execute("DELETE FROM tt_games WHERE match_id=? AND game_no=?", (mid, row["g"]))
        con.commit()


# --- finish + approvals ---------------------------------------------------
def finish_match(con, mid):
    """End live scoring -> pending_approval. The logger auto-approves; if that is everyone the
    match immediately becomes counted."""
    m = db.match_row(con, mid)
    if m["kind"] != "tt":
        validate_sets([(s["games_side1"], s["games_side2"]) for s in db.match_sets(con, mid)])
    con.execute("UPDATE matches SET status='pending_approval', finished_at=? WHERE id=?", (now(), mid))
    con.commit()
    if m["logger_id"]:
        approve(con, mid, m["logger_id"])
    else:
        _recount(con, mid)


def _all_approved(con, mid):
    parts = db.participants(con, mid)
    if not parts:
        return False
    appr = {r["player_id"] for r in con.execute(
        "SELECT player_id FROM approvals WHERE match_id=? AND action='approve'", (mid,)).fetchall()}
    return all(p in appr for p in parts)


def _recount(con, mid):
    """Move to counted iff every participant approved and nobody disputed; otherwise back off."""
    disputed = con.execute("SELECT 1 FROM approvals WHERE match_id=? AND action='dispute' LIMIT 1",
                           (mid,)).fetchone()
    m = db.match_row(con, mid)
    if m["status"] == "deleted":
        return
    if disputed:
        db.set_status(con, mid, "disputed")
    elif _all_approved(con, mid):
        db.set_status(con, mid, "counted")
    elif m["status"] == "counted":
        db.set_status(con, mid, "pending_approval")   # an approval was withdrawn -> ratings roll back


def approve(con, mid, pid):
    con.execute("DELETE FROM approvals WHERE match_id=? AND player_id=?", (mid, pid))
    con.execute("INSERT INTO approvals(match_id, player_id, action, approved_at) VALUES(?,?, 'approve', ?)",
                (mid, pid, now()))
    con.commit()
    _recount(con, mid)


def unapprove(con, mid, pid):
    """Withdraw an approval. If the match was counted, it drops to pending_approval and its rating
    contribution disappears on the next read (ROLLBACK)."""
    con.execute("DELETE FROM approvals WHERE match_id=? AND player_id=? AND action='approve'", (mid, pid))
    con.commit()
    _recount(con, mid)


def dispute(con, mid, pid, reason=None):
    con.execute("DELETE FROM approvals WHERE match_id=? AND player_id=?", (mid, pid))
    con.execute("INSERT INTO approvals(match_id, player_id, action, reason, approved_at) "
                "VALUES(?,?, 'dispute', ?, ?)", (mid, pid, reason, now()))
    con.commit()
    _recount(con, mid)


# --- freeze / resume (each needs every participant) -----------------------
def _all_requested(con, mid, kind):
    parts = db.participants(con, mid)
    if not parts:
        return False
    reqs = {r["player_id"] for r in con.execute(
        "SELECT player_id FROM freeze_requests WHERE match_id=? AND kind=?", (mid, kind)).fetchall()}
    return all(p in reqs for p in parts)


def freeze_request(con, mid, pid):
    con.execute("INSERT OR REPLACE INTO freeze_requests(match_id, player_id, kind, approved_at) "
                "VALUES(?,?, 'freeze', ?)", (mid, pid, now())) if not db._is_pg() else con.execute(
        "INSERT INTO freeze_requests(match_id, player_id, kind, approved_at) VALUES(?,?, 'freeze', ?) "
        "ON CONFLICT (match_id, player_id, kind) DO UPDATE SET approved_at=EXCLUDED.approved_at",
        (mid, pid, now()))
    con.commit()
    if _all_requested(con, mid, "freeze"):
        db.set_status(con, mid, "frozen")
        con.execute("DELETE FROM freeze_requests WHERE match_id=? AND kind='freeze'", (mid,))
        con.commit()


def resume_request(con, mid, pid):
    con.execute("INSERT OR REPLACE INTO freeze_requests(match_id, player_id, kind, approved_at) "
                "VALUES(?,?, 'resume', ?)", (mid, pid, now())) if not db._is_pg() else con.execute(
        "INSERT INTO freeze_requests(match_id, player_id, kind, approved_at) VALUES(?,?, 'resume', ?) "
        "ON CONFLICT (match_id, player_id, kind) DO UPDATE SET approved_at=EXCLUDED.approved_at",
        (mid, pid, now()))
    con.commit()
    if _all_requested(con, mid, "resume"):
        db.set_status(con, mid, "live")
        con.execute("DELETE FROM freeze_requests WHERE match_id=? AND kind='resume'", (mid,))
        con.commit()


# --- delete ---------------------------------------------------------------
def delete_match(con, mid):
    if not db.match_row(con, mid):
        raise ValueError("no such match")
    db.set_status(con, mid, "deleted")
    return "deleted"


if __name__ == "__main__":
    con = db.connect(":memory:")
    con.executescript(db.SCHEMA)
    a, b = db.gen_uuid(), db.gen_uuid()
    db.create_player(con, a, "A"); db.create_player(con, b, "B")
    assert legal_set(7, 6) and not legal_set(6, 5)
    # score a match with NO group; counts only after BOTH approve
    mid = start_match(con, None, "singles", [a], [b], [], a)
    edit_sets(con, mid, [(6, 4)])
    finish_match(con, mid)                                  # logger a auto-approves
    assert db.match_row(con, mid)["status"] == "pending_approval"
    approve(con, mid, b)
    assert db.match_row(con, mid)["status"] == "counted"
    assert db.rating_state(con)["singles"][a] > 1200
    # withdraw approval -> rating rolls back
    unapprove(con, mid, b)
    assert db.match_row(con, mid)["status"] == "pending_approval"
    assert db.rating_state(con)["singles"].get(a, 1200) == 1200
    print("OK logic")
