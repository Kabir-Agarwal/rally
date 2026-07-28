"""Per-request DB round-trip budget.

MEASURED on the live deployment (near-empty DB, warm function): /api/leaderboard 1.44s and
/api/live 1.03s against /api/auth/config (no DB, no auth) at 0.26s. The cost was not slow
queries — it was the NUMBER of sequential round trips to Supabase Postgres, and on the
unfiltered leaderboard that number grew with the total number of players in the whole app
(one friendships lookup per row).

These tests count con.execute() calls. The count is backend-independent, and on Postgres each
one is a network round trip, so a regression here is a direct latency regression.
"""
import collections

import pytest

from conftest import _fresh_app, signin


class _Counting:
    """Wraps a connection and counts queries. Only .execute is intercepted."""

    def __init__(self, con, stats):
        self._con, self._stats = con, stats

    def execute(self, sql, params=()):
        self._stats["n"] += 1
        self._stats["sql"].append(" ".join(str(sql).split())[:90])
        return self._con.execute(sql, params)

    def __getattr__(self, k):
        return getattr(self._con, k)


@pytest.fixture
def counted(tmp_path):
    """A client whose DB round trips are counted, plus a helper to measure one request."""
    from fastapi.testclient import TestClient
    appmod = _fresh_app(tmp_path)
    stats = collections.Counter()
    stats["sql"] = []
    plain = appmod.db.connect

    def counting_connect(path=tmp_path / "t.db"):
        stats["conn"] += 1
        return _Counting(plain(path), stats)

    c = TestClient(appmod.app)

    def measure(path, headers):
        stats["n"] = 0
        stats["conn"] = 0
        stats["sql"] = []
        appmod.db.connect = counting_connect
        try:
            r = c.get(path, headers=headers)
        finally:
            appmod.db.connect = plain
        assert r.status_code == 200, r.text
        return stats["n"], list(stats["sql"])

    c.measure = measure
    c.appmod = appmod
    c.plain = plain
    c.tmp_path = tmp_path
    return c


def _add_players(c, n, tag="a"):
    con = c.plain(c.tmp_path / "t.db")
    for i in range(n):
        c.appmod.db.create_player(con, f"extra-{tag}-{i}", f"Extra{tag}{i}", None)
    con.commit()
    con.close()


def test_leaderboard_query_count_does_not_grow_with_players(counted):
    """The N+1 that made the unfiltered board cost one round trip per player in the app."""
    c = counted
    me, h = signin(c, "me", "Me")
    signin(c, "friend", "Friend")
    c.post("/api/friend/request", json={"id": "friend"}, headers=h)

    _add_players(c, 3, "few")
    few, _ = c.measure("/api/leaderboard?mode=singles", h)
    _add_players(c, 40, "many")
    many, sql = c.measure("/api/leaderboard?mode=singles", h)

    assert c.get("/api/leaderboard?mode=singles", headers=h).json()  # sanity: still serves rows
    assert many == few, (
        f"leaderboard round trips grew {few} -> {many} when 40 players were added; "
        f"queries: {collections.Counter(sql).most_common(4)}")
    # A hard ceiling too, so the endpoint can't quietly creep back up.
    assert many <= 6, f"leaderboard uses {many} round trips: {sql}"


def _add_counted_matches(c, n, a, b):
    """n finished, fully-approved (status='counted') singles matches between a and b."""
    con = c.plain(c.tmp_path / "t.db")
    logic = c.appmod.logic
    for _ in range(n):
        mid = logic.start_match(con, None, "singles", [a], [b], [], a)
        logic.edit_sets(con, mid, [(6, 4)])
        logic.finish_match(con, mid)
        logic.approve(con, mid, a)
        logic.approve(con, mid, b)
    con.commit()
    con.close()


def test_leaderboard_query_count_does_not_grow_with_matches(counted):
    """The N+1 that actually kept /api/leaderboard at ~1.5s.

    The players axis was already covered above, so this one stayed invisible: rating_state()
    replayed every counted match and fetched THAT match's players/sets/point tally one match at a
    time — 3 round trips per counted match in the whole app. Guard the matches axis too.
    """
    c = counted
    a, ha = signin(c, "a", "A")
    b, hb = signin(c, "b", "B")

    _add_counted_matches(c, 2, a, b)
    few, _ = c.measure("/api/leaderboard?mode=singles", ha)
    _add_counted_matches(c, 12, a, b)
    many, sql = c.measure("/api/leaderboard?mode=singles", ha)

    assert many == few, (
        f"leaderboard round trips grew {few} -> {many} when 12 matches were added; "
        f"queries: {collections.Counter(sql).most_common(5)}")
    # Fixed budget, none of which scale with rows: 1 auth/me player + 5 for the rating rebuild
    # (matches, match_players, match_sets, tt_games, point_logs) + live ids + the board's players
    # + friendships. Was 1 + 3*(counted matches).
    assert many <= 9, f"leaderboard uses {many} round trips: {sql}"
    # sanity: those matches really are counted, so we measured the loaded path, not an empty one
    rows = c.get("/api/leaderboard?mode=singles", headers=ha).json()["rows"]
    assert any(r["n"] for r in rows), "no matches counted toward ratings — test measured nothing"


def test_leaderboard_still_reports_relationships_correctly(counted):
    """The batched friend_map must give the SAME answers the per-row query gave."""
    c = counted
    me, h = signin(c, "me", "Me")
    signin(c, "fr", "Fr")
    signin(c, "inc", "Inc")
    signin(c, "no", "No")
    c.post("/api/friend/request", json={"id": "fr"}, headers=h)           # -> sent
    c.post("/api/friend/accept", json={"id": "me"}, headers={"Authorization": _b("fr")})
    c.post("/api/friend/request", json={"id": "me"}, headers={"Authorization": _b("inc")})
    rows = c.get("/api/leaderboard?mode=singles", headers=h).json()
    by = {r["id"]: r["rel"] for r in rows["ranked"] + rows["provisional"]}
    assert by["me"] == "you"
    assert by["fr"] == "friend"
    assert by["inc"] == "incoming"
    assert by["no"] == "none"


def _b(sub):
    from conftest import bearer
    return bearer(sub)


def test_live_skips_the_rating_rebuild_when_nothing_is_live(counted):
    """rating_state() scans every counted match and rebuilds all ratings. With no live match
    there is no win_prob to compute, so that scan is pure wasted latency on every Live poll."""
    c = counted
    a, ha = signin(c, "a", "A")
    b, hb = signin(c, "b", "B")
    idle, idle_sql = c.measure("/api/live", ha)
    assert not any("status='counted'" in s for s in idle_sql), (
        f"/api/live rebuilt ratings with nothing live: {idle_sql}")

    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                 headers=ha).json()["id"]
    busy, busy_sql = c.measure("/api/live", ha)
    assert any("status='counted'" in s for s in busy_sql), (
        "/api/live must still compute ratings when a match IS live (win_prob)")
    assert c.get("/api/live", headers=ha).json()["matches"][0]["win_prob"], "win_prob missing"
    assert busy > idle


def test_me_is_a_single_query(counted):
    """/api/me is on the boot path — it must stay one round trip."""
    c = counted
    me, h = signin(c, "me", "Me")
    n, sql = c.measure("/api/me", h)
    assert n == 1, f"/api/me used {n} round trips: {sql}"
