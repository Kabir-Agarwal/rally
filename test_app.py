"""App-level tests: public vs private API access, live feed, end-to-end flow."""
import importlib
import db as dbmod


def client(tmp_path):
    # point the DB at a temp file, then (re)import app fresh
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    # patch get_con to use the temp path
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    from fastapi.testclient import TestClient
    return TestClient(appmod.app)


def test_public_vs_private_global_leaderboard(tmp_path):
    c = client(tmp_path)
    priv = c.post("/api/group/create", json={"name": "Priv"}).json()["code"]
    pub = c.post("/api/group/create", json={"name": "Pub"}).json()["code"]
    # add a player to each
    c.post(f"/g/{priv}/api/player", json={"name": "Secret"})
    c.post(f"/g/{pub}/api/player", json={"name": "Shown"})
    # make pub public
    c.post(f"/g/{pub}/api/public", json={"is_public": True})
    gl = c.get("/api/global/leaderboard?mode=singles").json()
    names = [r["name"] for r in gl["ranked"] + gl["provisional"]]
    assert "Shown" in names and "Secret" not in names


def test_live_feed_shows_public_groups_only(tmp_path):
    c = client(tmp_path)
    home = c.post("/api/group/create", json={"name": "Home"}).json()["code"]
    other = c.post("/api/group/create", json={"name": "Other"}).json()["code"]
    p1 = c.post(f"/g/{other}/api/player", json={"name": "X"}).json()["id"]
    p2 = c.post(f"/g/{other}/api/player", json={"name": "Y"}).json()["id"]
    c.post(f"/g/{other}/api/match/start", json={"kind": "singles", "side1": [p1], "side2": [p2], "logger": p1})
    # other is private -> not in home's public feed
    feed = c.get(f"/g/{home}/api/live").json()
    assert feed["public"] == []
    c.post(f"/g/{other}/api/public", json={"is_public": True})
    feed = c.get(f"/g/{home}/api/live").json()
    assert len(feed["public"]) == 1 and feed["public"][0]["group"] == "Other"


def test_end_to_end_singles_flow(tmp_path):
    c = client(tmp_path)
    code = c.post("/api/group/create", json={"name": "E2E"}).json()["code"]
    a = c.post(f"/g/{code}/api/player", json={"name": "Ann"}).json()["id"]
    b = c.post(f"/g/{code}/api/player", json={"name": "Bob"}).json()["id"]
    mid = c.post(f"/g/{code}/api/match/start",
                 json={"kind": "singles", "side1": [a], "side2": [b], "logger": a}).json()["id"]
    c.post(f"/g/{code}/api/match/{mid}/sets", json={"sets": [[6, 4], [6, 3]]})
    r = c.post(f"/g/{code}/api/match/{mid}/finish", json={"logger": a}).json()
    assert r["status"] == "pending_approval"
    c.post(f"/g/{code}/api/match/{mid}/approve", json={"player": b})
    lb = c.get(f"/g/{code}/api/leaderboard?scope=group&mode=singles").json()
    winner = [x for x in lb["provisional"] if x["name"] == "Ann"][0]
    assert winner["rating"] > 1200


def test_per_point_updates_sets(tmp_path):
    c = client(tmp_path)
    code = c.post("/api/group/create", json={"name": "PP"}).json()["code"]
    a = c.post(f"/g/{code}/api/player", json={"name": "A"}).json()["id"]
    b = c.post(f"/g/{code}/api/player", json={"name": "B"}).json()["id"]
    mid = c.post(f"/g/{code}/api/match/start",
                 json={"kind": "singles", "side1": [a], "side2": [b], "logger": a}).json()["id"]
    for _ in range(4):
        v = c.post(f"/g/{code}/api/match/{mid}/point", json={"winner_side": 1}).json()
    assert v["per_point"] and v["sets"][0]["g1"] == 1  # 4 points -> 1 game to side1
