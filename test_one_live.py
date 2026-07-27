"""A player can be in only ONE live match at a time — now enforced GLOBALLY (no group needed)."""
import sqlite3
import db
import logic
import pytest


def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    return con


def mkp(con, name):
    pid = db.gen_uuid(); db.create_player(con, pid, name); return pid


def test_singles_rejects_player_already_live():
    con = mem()
    a, b, c = (mkp(con, n) for n in ["Ann", "Bob", "Cara"])
    logic.start_match(con, None, "singles", [a], [b], [], a)
    with pytest.raises(ValueError) as e:
        logic.start_match(con, None, "singles", [a], [c], [], a)
    assert "Ann" in str(e.value) and "live match" in str(e.value)
    d = mkp(con, "Dan")
    assert logic.start_match(con, None, "singles", [c], [d], [], c)


def test_triple_threat_rejects_busy_player():
    con = mem()
    a, b, c, d, e = (mkp(con, n) for n in ["A", "B", "C", "D", "E"])
    logic.start_match(con, None, "singles", [a], [b], [], a)
    with pytest.raises(ValueError) as ex:
        logic.start_match(con, None, "tt", [], [], [a, c, d], a)
    assert "A" in str(ex.value)
    assert logic.start_match(con, None, "tt", [], [], [c, d, e], c)


def test_finishing_frees_the_player():
    con = mem()
    a, b, c = (mkp(con, n) for n in ["A", "B", "C"])
    m = logic.start_match(con, None, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m)
    assert logic.start_match(con, None, "singles", [a], [c], [], a)


def test_past_result_does_not_conflict_with_live():
    con = mem()
    a, b, c = (mkp(con, n) for n in ["A", "B", "C"])
    logic.start_match(con, None, "singles", [a], [b], [], a)
    mid = logic.save_played(con, None, "singles", [a], [c], [], [(6, 3)], a)
    assert db.match_row(con, mid)["status"] in ("pending_approval", "counted")
