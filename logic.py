"""Match lifecycle + approval state machine. Pure over a sqlite connection."""
from __future__ import annotations
import db
from db import now, deadline_24h


# --- validation -----------------------------------------------------------
def legal_set(a, b):
    """A legal finished set: 6-0..6-4, 7-5, or 7-6."""
    hi, lo = max(a, b), min(a, b)
    if hi == 6 and lo <= 4:
        return True
    if hi == 7 and lo in (5, 6):
        return True
    return False


def validate_sets(sets):
    """Strict check at finish. Returns list of legal (g1,g2), raises on illegal."""
    clean = [(a, b) for a, b in sets if not (a == 0 and b == 0)]
    if not clean:
        raise ValueError("no sets played")
    if len(clean) > 5:
        raise ValueError("max 5 sets")
    for a, b in clean:
        if not legal_set(a, b):
            raise ValueError(f"illegal set {a}-{b}")
    return clean


# --- start (players + order locked here) ----------------------------------
def start_match(con, group_id, kind, side1, side2, rotation, logger_player_id, played_on=None):
    ts = now()
    cur = con.execute(
        "INSERT INTO matches(group_id, played_on, kind, status, logger_player_id, created_at, started_at)"
        " VALUES(?,?,?, 'live', ?, ?, ?)",
        (group_id, played_on or ts[:10], kind, logger_player_id, ts, ts),
    )
    mid = cur.lastrowid
    if kind == "tt":
        for pos, pid in enumerate(rotation, start=1):
            con.execute(
                "INSERT INTO match_players(match_id, player_id, side, rotation_pos) VALUES(?,?,?,?)",
                (mid, pid, 0, pos),
            )
    else:
        for pid in side1:
            con.execute("INSERT INTO match_players(match_id, player_id, side) VALUES(?,?,1)", (mid, pid))
        for pid in side2:
            con.execute("INSERT INTO match_players(match_id, player_id, side) VALUES(?,?,2)", (mid, pid))
    con.commit()
    return mid


def save_played(con, group_id, kind, side1, side2, rotation, sets, logger_player_id, played_on=None):
    """'Already played? Final score' — create match and send straight to approval."""
    mid = start_match(con, group_id, kind, side1, side2, rotation, logger_player_id, played_on)
    if kind != "tt":
        _write_sets(con, mid, sets)
    finish_match(con, mid, logger_player_id)
    return mid


# --- live scoring edits ---------------------------------------------------
def _write_sets(con, mid, sets):
    con.execute("DELETE FROM match_sets WHERE match_id=?", (mid,))
    for i, (a, b) in enumerate(sets, start=1):
        con.execute(
            "INSERT INTO match_sets(match_id, set_no, games_side1, games_side2) VALUES(?,?,?,?)",
            (mid, i, int(a), int(b)),
        )
    con.commit()


def edit_sets(con, mid, sets):
    m = db.match_row(con, mid)
    if m["status"] not in ("live", "pending_approval"):
        raise ValueError("only live or pending matches are editable")
    _write_sets(con, mid, sets)
    if m["status"] == "pending_approval":
        _reset_approvals(con, mid)  # editing a pending match resets approvals


def log_point(con, mid, winner_side, server_player_id):
    seq = con.execute("SELECT COALESCE(MAX(seq),0)+1 FROM point_logs WHERE match_id=?", (mid,)).fetchone()[0]
    con.execute(
        "INSERT INTO point_logs(match_id, seq, winner_side, server_player_id) VALUES(?,?,?,?)",
        (mid, seq, winner_side, server_player_id),
    )
    con.commit()


def log_tt_game(con, mid, server_player_id, winner_player_id):
    g = con.execute("SELECT COALESCE(MAX(game_no),0)+1 FROM tt_games WHERE match_id=?", (mid,)).fetchone()[0]
    con.execute(
        "INSERT INTO tt_games(match_id, game_no, server_player_id, winner_player_id) VALUES(?,?,?,?)",
        (mid, g, server_player_id, winner_player_id),
    )
    con.commit()


def undo_tt_game(con, mid):
    row = con.execute("SELECT MAX(game_no) g FROM tt_games WHERE match_id=?", (mid,)).fetchone()
    if row and row["g"]:
        con.execute("DELETE FROM tt_games WHERE match_id=? AND game_no=?", (mid, row["g"]))
        con.commit()


# --- approvals ------------------------------------------------------------
def _player_ids(con, mid):
    return [r["player_id"] for r in db.match_players(con, mid)]


def _make_approvals(con, mid, action, auto_player_id):
    con.execute("DELETE FROM approvals WHERE match_id=?", (mid,))
    dl = deadline_24h()
    for pid in _player_ids(con, mid):
        approved = now() if pid == auto_player_id else None
        con.execute(
            "INSERT INTO approvals(match_id, player_id, action, approved_at, deadline) VALUES(?,?,?,?,?)",
            (mid, pid, action, approved, dl),
        )
    con.commit()


def _reset_approvals(con, mid):
    """Re-arm finish approvals after a pending match is edited (logger re-auto-approves)."""
    m = db.match_row(con, mid)
    _make_approvals(con, mid, "finish", m["logger_player_id"])


def approvals_of(con, mid):
    return con.execute("SELECT a.*, p.name FROM approvals a JOIN players p ON p.id=a.player_id "
                       "WHERE a.match_id=? ORDER BY a.player_id", (mid,)).fetchall()


def _all_approved(con, mid):
    rows = con.execute("SELECT approved_at FROM approvals WHERE match_id=?", (mid,)).fetchall()
    return bool(rows) and all(r["approved_at"] for r in rows)


def finish_match(con, mid, logger_player_id):
    """Mark finished -> pending_approval; logger auto-approves; others get chips."""
    m = db.match_row(con, mid)
    if m["kind"] != "tt":
        validate_sets([(s["games_side1"], s["games_side2"]) for s in db.match_sets(con, mid)])
    con.execute("UPDATE matches SET status='pending_approval' WHERE id=?", (mid,))
    con.commit()
    _make_approvals(con, mid, "finish", logger_player_id)
    _try_finalize(con, mid)  # solo logger / already-all-approved short-circuits


def approve(con, mid, player_id):
    con.execute("UPDATE approvals SET approved_at=? WHERE match_id=? AND player_id=? AND approved_at IS NULL",
                (now(), mid, player_id))
    con.commit()
    _try_finalize(con, mid)


def _try_finalize(con, mid):
    m = db.match_row(con, mid)
    if not _all_approved(con, mid):
        return
    action = con.execute("SELECT action FROM approvals WHERE match_id=? LIMIT 1", (mid,)).fetchone()["action"]
    if action == "finish":
        con.execute("UPDATE matches SET status='finished', finished_at=? WHERE id=?", (now(), mid))
        con.execute("DELETE FROM approvals WHERE match_id=?", (mid,))
        con.commit()
    elif action == "delete":
        _hard_delete(con, mid)


def check_deadlines(con):
    """Auto-finalize FINISH approvals past deadline. Delete approvals NEVER auto-finalize."""
    due = con.execute(
        "SELECT DISTINCT match_id FROM approvals WHERE action='finish' AND deadline < ?", (now(),)
    ).fetchall()
    for r in due:
        mid = r["match_id"]
        con.execute("UPDATE matches SET status='finished', finished_at=COALESCE(finished_at,?) WHERE id=?",
                    (now(), mid))
        con.execute("DELETE FROM approvals WHERE match_id=?", (mid,))
    if due:
        con.commit()


# --- delete ---------------------------------------------------------------
def _hard_delete(con, mid):
    for t in ("match_players", "match_sets", "tt_games", "point_logs", "approvals"):
        con.execute(f"DELETE FROM {t} WHERE match_id=?", (mid,))
    con.execute("DELETE FROM matches WHERE id=?", (mid,))
    con.commit()


def delete_match(con, mid, requester_player_id):
    """Live -> instant delete. Finished -> delete_requested needing ALL players (no auto)."""
    m = db.match_row(con, mid)
    if m["status"] == "live":
        _hard_delete(con, mid)
        return "deleted"
    if m["status"] in ("finished", "pending_approval", "delete_requested"):
        con.execute("UPDATE matches SET status='delete_requested' WHERE id=?", (mid,))
        con.commit()
        _make_approvals(con, mid, "delete", auto_player_id=None)  # no auto-approve
        return "requested"
    raise ValueError("cannot delete")


if __name__ == "__main__":
    con = db.connect(":memory:")
    con.executescript(db.SCHEMA)
    gid, _ = db.create_group(con, "T")
    a = db.add_player(con, gid, "A")
    b = db.add_player(con, gid, "B")

    # legal set validation
    assert legal_set(7, 6) and legal_set(7, 5) and legal_set(6, 0)
    assert not legal_set(6, 5) and not legal_set(8, 6)

    # start locks players; finish -> pending; logger auto-approved, B pending
    mid = start_match(con, gid, "singles", [a], [b], [], a)
    edit_sets(con, mid, [(6, 4)])
    finish_match(con, mid, a)
    assert db.match_row(con, mid)["status"] == "pending_approval"
    aps = {r["player_id"]: r["approved_at"] for r in approvals_of(con, mid)}
    assert aps[a] and not aps[b], "logger auto, other pending"

    # B approves -> finished + rated
    approve(con, mid, b)
    assert db.match_row(con, mid)["status"] == "finished"
    st = db.rating_state(con, gid)
    assert st["singles"][a] > 1200 and st["singles"][b] < 1200

    # edit of pending resets approvals
    mid2 = start_match(con, gid, "singles", [a], [b], [], a)
    edit_sets(con, mid2, [(6, 4)])
    finish_match(con, mid2, a)
    approve(con, mid2, b)  # would finish... but let's test reset before approve
    # fresh pending for reset test
    mid3 = start_match(con, gid, "singles", [a], [b], [], a)
    edit_sets(con, mid3, [(6, 4)])
    finish_match(con, mid3, a)
    edit_sets(con, mid3, [(6, 3)])  # edit while pending
    aps = {r["player_id"]: r["approved_at"] for r in approvals_of(con, mid3)}
    assert aps[a] and not aps[b], "reset: logger re-auto, other pending again"

    # delete live = instant
    mlive = start_match(con, gid, "singles", [a], [b], [], a)
    assert delete_match(con, mlive, a) == "deleted"
    assert db.match_row(con, mlive) is None

    # delete finished = request, needs ALL (no auto)
    r = delete_match(con, mid, a)
    assert r == "requested" and db.match_row(con, mid)["status"] == "delete_requested"
    aps = approvals_of(con, mid)
    assert all(not x["approved_at"] for x in aps), "delete: no auto-approve"
    # still counts while requested
    st = db.rating_state(con, gid)
    assert mid in [m["id"] for m in con.execute("SELECT id FROM matches WHERE status='delete_requested'")]
    # both approve -> gone
    approve(con, mid, a)
    approve(con, mid, b)
    assert db.match_row(con, mid) is None

    print("OK logic")
