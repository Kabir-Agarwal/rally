"""Match lifecycle (v2: immediate results, no approval gate). Pure over a db connection."""
from __future__ import annotations
import db
from db import now


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
    finish_match(con, mid)
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
    if m["status"] not in ("live", "finished"):
        raise ValueError("match is not editable")
    _write_sets(con, mid, sets)  # v2: no approval reset — finished results just recompute


def log_point(con, mid, winner_side, server_player_id):
    seq = con.execute("SELECT COALESCE(MAX(seq),0)+1 FROM point_logs WHERE match_id=?", (mid,)).fetchone()[0]
    con.execute(
        "INSERT INTO point_logs(match_id, seq, winner_side, server_player_id) VALUES(?,?,?,?)",
        (mid, seq, winner_side, server_player_id),
    )
    con.commit()


def log_tt_game(con, mid, server_player_id, winner_player_id, receiver_player_id=None):
    g = con.execute("SELECT COALESCE(MAX(game_no),0)+1 FROM tt_games WHERE match_id=?", (mid,)).fetchone()[0]
    con.execute(
        "INSERT INTO tt_games(match_id, game_no, server_player_id, receiver_player_id, winner_player_id)"
        " VALUES(?,?,?,?,?)",
        (mid, g, server_player_id, receiver_player_id, winner_player_id),
    )
    con.commit()


def undo_tt_game(con, mid):
    row = con.execute("SELECT MAX(game_no) g FROM tt_games WHERE match_id=?", (mid,)).fetchone()
    if row and row["g"]:
        con.execute("DELETE FROM tt_games WHERE match_id=? AND game_no=?", (mid, row["g"]))
        con.commit()


# --- finish (v2: immediate, no approval gate) -----------------------------
def finish_match(con, mid):
    """End a live match -> finished. Counts toward ratings IMMEDIATELY (no approvals)."""
    m = db.match_row(con, mid)
    if m["kind"] != "tt":
        validate_sets([(s["games_side1"], s["games_side2"]) for s in db.match_sets(con, mid)])
    con.execute("UPDATE matches SET status='finished', finished_at=? WHERE id=?", (now(), mid))
    con.commit()


# --- delete (v2: immediate soft-delete; admin can restore) ----------------
def delete_match(con, mid):
    """Soft-delete immediately (any member). Hidden everywhere + out of ratings at once."""
    if not db.match_row(con, mid):
        raise ValueError("no such match")
    db.set_deleted(con, mid, True)
    return "deleted"


def hard_delete(con, mid):
    """Permanent removal (used by group/player cascades)."""
    for t in ("match_players", "match_sets", "tt_games", "point_logs", "approvals"):
        con.execute(f"DELETE FROM {t} WHERE match_id=?", (mid,))
    con.execute("DELETE FROM matches WHERE id=?", (mid,))
    con.commit()


# --- admin god-mode (void/unvoid, restore, edit) --------------------------
def admin_delete_match(con, mid):
    """Admin soft-delete of any match (restorable)."""
    if not db.match_row(con, mid):
        raise ValueError("no such match")
    db.set_deleted(con, mid, True)


def admin_restore_match(con, mid):
    """Restore a soft-deleted match."""
    if not db.match_row(con, mid):
        raise ValueError("no such match")
    db.set_deleted(con, mid, False)


def admin_void_match(con, mid):
    """Void a match: kept and visible, but EXCLUDED from rating recompute-on-read."""
    if not db.match_row(con, mid):
        raise ValueError("no such match")
    db.set_voided(con, mid, True)


def admin_unvoid_match(con, mid):
    """Unvoid: the match counts toward ratings again."""
    if not db.match_row(con, mid):
        raise ValueError("no such match")
    db.set_voided(con, mid, False)


def admin_edit_match(con, mid, sets=None, played_on=None, kind=None):
    """Edit any match's sets, date, and/or kind. Kind only if it fits the roster."""
    m = db.match_row(con, mid)
    if not m:
        raise ValueError("no such match")
    if kind and kind != m["kind"]:
        s1, s2, rot = db.sides(con, mid)
        ok = ((kind == "singles" and len(s1) == 1 and len(s2) == 1)
              or (kind == "doubles" and len(s1) == 2 and len(s2) == 2)
              or (kind == "tt" and len(rot) == 3))
        if not ok:
            raise ValueError("kind does not match this match's players")
        con.execute("UPDATE matches SET kind=? WHERE id=?", (kind, mid))
    target_kind = kind or m["kind"]
    if sets is not None and target_kind != "tt":
        clean = validate_sets([(int(a), int(b)) for a, b in sets])
        _write_sets(con, mid, clean)
    if played_on:
        con.execute("UPDATE matches SET played_on=? WHERE id=?", (played_on, mid))
    con.commit()


if __name__ == "__main__":
    con = db.connect(":memory:")
    con.executescript(db.SCHEMA)
    gid, _ = db.create_group(con, "T")
    a = db.add_player(con, gid, "A")
    b = db.add_player(con, gid, "B")

    # legal set validation
    assert legal_set(7, 6) and legal_set(7, 5) and legal_set(6, 0)
    assert not legal_set(6, 5) and not legal_set(8, 6)

    # v2: finish -> immediately finished + rated (no approval gate)
    mid = start_match(con, gid, "singles", [a], [b], [], a)
    edit_sets(con, mid, [(6, 4)])
    finish_match(con, mid)
    assert db.match_row(con, mid)["status"] == "finished"
    st = db.rating_state(con, gid)
    assert st["singles"][a] > 1200 and st["singles"][b] < 1200

    # delete = immediate soft-delete; out of ratings at once; admin can restore
    delete_match(con, mid)
    assert db.match_row(con, mid)["deleted"] == 1
    st = db.rating_state(con, gid)
    assert st["singles"].get(a, 1200) == 1200, "deleted match excluded from ratings"
    admin_restore_match(con, mid)
    assert db.match_row(con, mid)["deleted"] == 0
    assert db.rating_state(con, gid)["singles"][a] > 1200, "restore brings it back"

    # void = kept but excluded from recompute; unvoid restores it
    admin_void_match(con, mid)
    assert db.rating_state(con, gid)["singles"].get(a, 1200) == 1200
    admin_unvoid_match(con, mid)
    assert db.rating_state(con, gid)["singles"][a] > 1200

    # delete of a live match is immediate too
    mlive = start_match(con, gid, "singles", [a], [b], [], a)
    assert delete_match(con, mlive) == "deleted"
    assert db.match_row(con, mlive)["deleted"] == 1

    print("OK logic")
