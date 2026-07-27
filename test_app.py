"""App-level tests: global vs ?group= leaderboard, live feed, end-to-end scoring flow (new model)."""
from conftest import signin


def _two(c):
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    return a, ha, b, hb


def _score_counted(c, a, ha, b, hb, group=None):
    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": group},
                 headers=ha).json()["id"]
    c.post(f"/api/match/{mid}/sets", json={"sets": [[6, 4], [6, 3]]}, headers=ha)
    c.post(f"/api/match/{mid}/finish", json={}, headers=ha)          # logger a auto-approves
    c.post(f"/api/match/{mid}/approve", json={}, headers=hb)         # b approves -> counted
    return mid


def test_global_vs_group_leaderboard_filter(app_client):
    c = app_client
    a, ha, b, hb = _two(c)
    code = c.post("/api/group/create", json={"name": "G"}, headers=ha).json()["code"]
    c.post("/api/group/join", json={"code": code}, headers=hb)   # public group -> instant member
    _score_counted(c, a, ha, b, hb, group=code)
    glob = c.get("/api/leaderboard?mode=singles").json()
    grp = c.get(f"/api/leaderboard?mode=singles&group={code}").json()
    names_glob = [r["name"] for r in glob["ranked"] + glob["provisional"]]
    assert "Ann" in names_glob and "Bob" in names_glob          # global sees everyone
    assert grp["scope"] == "group"                              # ?group= filters to that group
    gnames = [r["name"] for r in grp["ranked"] + grp["provisional"]]
    assert "Ann" in gnames and "Bob" in gnames                  # both are members of G


def test_leaderboard_carries_code_and_relationship(app_client):
    c = app_client
    a, ha, b, hb = _two(c)

    def rel_of(headers, name):
        lb = c.get("/api/leaderboard?mode=singles", headers=headers).json()
        row = [r for r in lb["ranked"] + lb["provisional"] if r["name"] == name][0]
        assert row["code"]                       # Name#CODE needs the code
        return row["rel"]

    assert rel_of(ha, "Ann") == "you"            # own row
    assert rel_of(ha, "Bob") == "none"           # stranger -> "not a friend"
    c.post("/api/friend/request", json={"id": b}, headers=ha)   # a -> b
    assert rel_of(ha, "Bob") == "sent"           # I sent it
    assert rel_of(hb, "Ann") == "incoming"       # b sees an incoming request
    c.post("/api/friend/accept", json={"id": a}, headers=hb)
    assert rel_of(ha, "Bob") == "friend" and rel_of(hb, "Ann") == "friend"


def test_live_feed_shows_my_live_match_no_group(app_client):
    c = app_client
    a, ha, b, hb = _two(c)
    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                 headers=ha).json()["id"]
    feed = c.get("/api/live", headers=ha).json()
    assert len(feed["matches"]) == 1 and feed["matches"][0]["group_id"] is None


def test_end_to_end_singles_counts_only_after_all_approve(app_client):
    c = app_client
    a, ha, b, hb = _two(c)
    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                 headers=ha).json()["id"]
    c.post(f"/api/match/{mid}/sets", json={"sets": [[6, 4], [6, 3]]}, headers=ha)
    r = c.post(f"/api/match/{mid}/finish", json={}, headers=ha).json()
    assert r["status"] == "pending_approval"               # logger approved, b hasn't
    lb = c.get("/api/leaderboard?mode=singles").json()
    assert all(x["name"] != "Ann" or x["rating"] == 1200 for x in lb["provisional"])  # not counted yet
    assert c.post(f"/api/match/{mid}/approve", json={}, headers=hb).json()["status"] == "counted"
    lb = c.get("/api/leaderboard?mode=singles").json()
    ann = [x for x in lb["provisional"] if x["name"] == "Ann"][0]
    assert ann["rating"] > 1200


def test_per_point_updates_sets(app_client):
    c = app_client
    a, ha, b, hb = _two(c)
    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                 headers=ha).json()["id"]
    for _ in range(4):
        v = c.post(f"/api/match/{mid}/point", json={"winner_side": 1}, headers=ha).json()
    assert v["per_point"] and v["sets"][0]["g1"] == 1
