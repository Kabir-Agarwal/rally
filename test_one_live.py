"""Task 6: a player can be in only ONE live match at a time — enforced on the server."""
import sqlite3
import db
import logic
import pytest


def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    db._RATING_CACHE.clear()
    return con


def test_singles_rejects_player_already_live():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c = (db.add_player(con, gid, n) for n in ["Ann", "Bob", "Cara"])
    logic.start_match(con, gid, "singles", [a], [b], [], a)   # Ann + Bob live
    with pytest.raises(ValueError) as e:
        logic.start_match(con, gid, "singles", [a], [c], [], a)   # Ann again
    assert "Ann" in str(e.value) and "live match" in str(e.value)
    # a free player can still start
    d = db.add_player(con, gid, "Dan")
    assert logic.start_match(con, gid, "singles", [c], [d], [], c)   # Cara + Dan ok


def test_triple_threat_rejects_busy_player():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c, d, e = (db.add_player(con, gid, n) for n in ["A", "B", "C", "D", "E"])
    logic.start_match(con, gid, "singles", [a], [b], [], a)   # A live
    with pytest.raises(ValueError) as ex:
        logic.start_match(con, gid, "tt", [], [], [a, c, d], a)   # A can't also be in TT
    assert "A" in str(ex.value)
    # a clean TT (c,d,e) is fine
    assert logic.start_match(con, gid, "tt", [], [], [c, d, e], c)


def test_finishing_frees_the_player():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c = (db.add_player(con, gid, n) for n in ["A", "B", "C"])
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m)   # A no longer live
    assert logic.start_match(con, gid, "singles", [a], [c], [], a)   # now allowed


def test_past_result_does_not_conflict_with_live():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c = (db.add_player(con, gid, n) for n in ["A", "B", "C"])
    logic.start_match(con, gid, "singles", [a], [b], [], a)          # A live
    # entering a PAST result for A is allowed (not a concurrent live match)
    mid = logic.save_played(con, gid, "singles", [a], [c], [], [(6, 3)], a)
    assert db.match_row(con, mid)["status"] == "finished"
