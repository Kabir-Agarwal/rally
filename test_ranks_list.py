"""Ranks is ONE list (2026-07-28).

Players with under 5 matches are no longer a separate "Minimum 5 matches" section — they sit in
the same list, greyed, unnumbered. The server therefore ships `rows` in display order:
ranked (5+ matches, numbered by rating) first, then under-5 players by rating.

`ranked`/`provisional` remain in the payload as views of the same rows, so nothing that reads
them breaks; these tests pin that they stay consistent with `rows`.
"""
import ratings
from conftest import signin


def _count_singles(c, a, ha, b, hb, n):
    """Play n counted singles matches between a and b (a always wins)."""
    for _ in range(n):
        mid = c.post("/api/match/start",
                     json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                     headers=ha).json()["id"]
        c.post(f"/api/match/{mid}/sets", json={"sets": [[6, 4]]}, headers=ha)
        c.post(f"/api/match/{mid}/finish", json={}, headers=ha)
        c.post(f"/api/match/{mid}/approve", json={}, headers=hb)


def test_payload_ships_one_ordered_row_list(app_client):
    c = app_client
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    signin(c, "z", "Zoe")                       # never plays: stays under 5
    _count_singles(c, a, ha, b, hb, ratings.MIN_MATCHES)

    lb = c.get("/api/leaderboard?mode=singles").json()
    assert "rows" in lb, "the client renders one list, so the server must ship one list"
    rows = lb["rows"]

    # rows == ranked + provisional, exactly, in that order
    assert rows == lb["ranked"] + lb["provisional"]
    # every player appears exactly once
    assert len(rows) == 3
    assert len({r["id"] for r in rows}) == 3

    ranked = [r for r in rows if not r["provisional"]]
    prov = [r for r in rows if r["provisional"]]
    assert {r["name"] for r in ranked} == {"Ann", "Bob"}, "5 matches each -> both ranked"
    assert [r["name"] for r in prov] == ["Zoe"], "0 matches -> under-5"

    # ranked block comes first and is numbered 1..N by descending rating
    assert [r["rank"] for r in ranked] == [1, 2]
    assert ranked[0]["rating"] >= ranked[1]["rating"]
    assert ranked[0]["name"] == "Ann", "the winner of every match should rank first"
    # under-5 rows carry the match count the UI shows as "N of 5"
    assert prov[0]["n"] == 0
    # ...and they sort after every ranked row
    assert rows.index(prov[0]) == len(ranked)


def test_under_five_is_flagged_not_hidden(app_client):
    """The greying is driven by `provisional` + `n`; the row must still carry everything the
    single list renders (name, rating, relationship, code) so it is fully tappable."""
    c = app_client
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    _count_singles(c, a, ha, b, hb, ratings.MIN_MATCHES - 1)      # one short of ranked

    rows = c.get("/api/leaderboard?mode=singles", headers=ha).json()["rows"]
    assert rows and all(r["provisional"] for r in rows), "4 matches is still under 5"
    for r in rows:
        assert r["n"] == ratings.MIN_MATCHES - 1
        assert {"id", "name", "real_name", "code", "rel", "rating", "n", "provisional"} <= set(r)
        assert "rank" not in r, "an under-5 row must not carry a rank number (the UI shows 'N of 5')"


def test_crossing_five_matches_moves_a_row_into_the_ranked_block(app_client):
    c = app_client
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    _count_singles(c, a, ha, b, hb, ratings.MIN_MATCHES - 1)
    before = c.get("/api/leaderboard?mode=singles").json()
    assert all(r["provisional"] for r in before["rows"])
    assert before["ranked"] == []

    _count_singles(c, a, ha, b, hb, 1)          # the 5th match
    after = c.get("/api/leaderboard?mode=singles").json()
    assert after["provisional"] == [], "5 matches -> nobody is provisional any more"
    assert [r["rank"] for r in after["rows"]] == [1, 2]
    assert after["rows"] == after["ranked"]


def test_live_flag_marks_only_players_in_a_live_match(app_client):
    """The board's `live` flag now comes from an EXISTS joined into the player query rather than
    a separate live_player_ids() round trip. Same answer, so pin the answer."""
    c = app_client
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    signin(c, "z", "Zoe")                       # not playing

    def live_by_id():
        return {r["id"]: r["live"] for r in c.get("/api/leaderboard?mode=singles").json()["rows"]}

    assert live_by_id() == {a: False, b: False, "z": False}, "nothing is live yet"

    mid = c.post("/api/match/start",
                 json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                 headers=ha).json()["id"]
    assert live_by_id() == {a: True, b: True, "z": False}, "only the two in the live match"

    c.post(f"/api/match/{mid}/sets", json={"sets": [[6, 4]]}, headers=ha)
    c.post(f"/api/match/{mid}/finish", json={}, headers=ha)
    c.post(f"/api/match/{mid}/approve", json={}, headers=hb)
    assert live_by_id() == {a: False, b: False, "z": False}, "finished match is no longer live"


def test_unranked_order_is_stable_across_a_rename(app_client):
    """P3: unranked players were ordered alphabetically, so renaming reshuffled the board for
    everyone. Order must follow join order (created_at, then code) and ignore the name."""
    c = app_client
    signin(c, "p1", "Zoe")          # joins first, but sorts LAST alphabetically
    signin(c, "p2", "Ann")
    signin(c, "p3", "Mia")

    def order():
        return [r["id"] for r in c.get("/api/leaderboard?mode=singles").json()["rows"]]

    before = order()
    # NOT the alphabetical order the board used to use — that would be Ann, Mia, Zoe.
    assert before != ["p2", "p3", "p1"], "unranked order must not be driven by game_name"

    # Rename the first player to sort last alphabetically, and the alphabetically-first to sort
    # last. Under the old ordering this reshuffled the board for everyone.
    c.post("/api/me/rename", json={"name": "Aaa"}, headers={"Authorization": _bearer("p1")})
    c.post("/api/me/rename", json={"name": "Zzz"}, headers={"Authorization": _bearer("p2")})
    assert order() == before, "a rename must not move anyone on the unranked list"

    # created_at is second-granular (db.now()), so same-second signups tie and the unique,
    # immutable `code` decides. Either way the order is total and rename-proof.
    rows = c.get("/api/leaderboard?mode=singles").json()["rows"]
    keys = [(r.get("created_at") or "", r["code"]) for r in rows]
    assert keys == sorted(keys), f"unranked rows must be ordered by (created_at, code): {keys}"


def _bearer(sub):
    from conftest import bearer
    return bearer(sub)
