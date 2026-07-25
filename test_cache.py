"""Task 2: cached ratings equal freshly-computed, cache invalidates on rating changes."""
import sqlite3
import db
import logic


def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    db._RATING_CACHE.clear()
    return con


def _finished(con, gid, a, b, sets):
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, sets)
    logic.finish_match(con, m)
    return m


def test_cached_equals_freshly_computed():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c = (db.add_player(con, gid, n) for n in "ABC")
    _finished(con, gid, a, b, [(6, 4)])
    _finished(con, gid, b, c, [(6, 3)])
    _finished(con, gid, a, c, [(7, 5)])
    cached = db.rating_state(con, gid)                     # builds + caches
    fresh = db.rating_state(con, gid, use_cache=False)     # bypasses cache
    assert cached["singles"] == fresh["singles"]
    assert cached["doubles"] == fresh["doubles"]
    assert cached["pairs"] == fresh["pairs"]


def test_cache_hit_returns_same_object_until_change():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    _finished(con, gid, a, b, [(6, 4)])
    s1 = db.rating_state(con, gid)
    s2 = db.rating_state(con, gid)
    assert s1 is s2, "unchanged rev -> served from cache (no rebuild)"
    # a new finished match bumps the rev -> cache rebuilds, numbers update
    before = s1["singles"][a]
    _finished(con, gid, a, b, [(6, 0)])
    s3 = db.rating_state(con, gid)
    assert s3 is not s1 and s3["singles"][a] != before
    assert s3["singles"] == db.rating_state(con, gid, use_cache=False)["singles"]


def test_void_and_delete_invalidate_cache():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = _finished(con, gid, a, b, [(6, 0)])
    assert db.rating_state(con, gid)["singles"][a] > 1200
    logic.admin_void_match(con, m)
    assert db.rating_state(con, gid)["singles"].get(a, 1200) == 1200      # cache saw the void
    assert db.rating_state(con, gid)["singles"] == db.rating_state(con, gid, use_cache=False)["singles"]
    logic.admin_unvoid_match(con, m)
    assert db.rating_state(con, gid)["singles"][a] > 1200
