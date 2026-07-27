"""Ratings are now recomputed-on-read from counted matches (the in-process rating cache + ratings_rev
were removed in the clean foundation). These tests assert the NEW behavior: correctness, and the
global vs ?group= filter. (Rewritten from the old cache tests — the cache no longer exists.)"""
import sqlite3
import db
import logic


def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    return con


def mkp(con, name):
    pid = db.gen_uuid(); db.create_player(con, pid, name); return pid


def counted(con, a, b, sets, group_id=None):
    m = logic.start_match(con, group_id, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, sets)
    logic.finish_match(con, m)
    for p in (a, b):
        logic.approve(con, m, p)
    return m


def test_only_counted_matches_affect_ratings():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = logic.start_match(con, None, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m)   # pending_approval (b hasn't approved)
    assert db.rating_state(con)["singles"].get(a, 1200) == 1200
    logic.approve(con, m, b)                                        # now counted
    assert db.rating_state(con)["singles"][a] > 1200


def test_global_vs_group_rating_filter():
    con = mem()
    a, b, c = mkp(con, "A"), mkp(con, "B"), mkp(con, "C")
    gid, _ = db.create_group(con, "G", a)
    counted(con, a, b, [(6, 0)], group_id=gid)     # in-group match
    counted(con, a, c, [(6, 0)], group_id=None)    # ungrouped match
    glob = db.rating_state(con)                     # all counted matches
    grp = db.rating_state(con, gid)                 # only group G's matches
    assert glob["singles_n"][a] == 2                # both count globally
    assert grp["singles_n"][a] == 1                 # only the in-group one for the group filter


def test_recompute_is_stable():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    counted(con, a, b, [(6, 4)])
    s1 = db.rating_state(con)["singles"][a]
    s2 = db.rating_state(con)["singles"][a]
    assert s1 == s2                                 # deterministic recompute-on-read
