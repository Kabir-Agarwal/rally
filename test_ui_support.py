"""Task 6 server support: /meta, win-probability in live feed, history date edit."""
import importlib
import db as dbmod


def _c(tmp_path):
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    from fastapi.testclient import TestClient
    c = TestClient(appmod.app)
    tok = "Bearer " + appmod.auth.mint_mock_token("u1", "u1@test")
    c.headers.update({"Authorization": tok, "X-Admin-Key": appmod.ADMIN_KEY})
    return c


def _group(c):
    code = c.post("/api/group/create", json={"name": "G"}).json()["code"]
    ids = [c.post(f"/g/{code}/api/player", json={"name": n}).json()["id"] for n in ["Ann", "Bob", "Cara"]]
    return code, ids


def test_meta_shape_zero_based(tmp_path):
    c = _c(tmp_path)
    code, (a, b, cc) = _group(c)
    meta = c.get(f"/g/{code}/api/meta").json()
    assert {"players", "pairs", "pair_provisional"} <= set(meta)
    p = meta["players"][0]
    assert {"id", "name", "live", "singles", "singles_n", "doubles", "doubles_n"} <= set(p)
    assert p["singles"] == 0 and p["singles_n"] == 0        # 0-based display, no matches


def test_live_has_win_prob(tmp_path):
    c = _c(tmp_path)
    code, (a, b, cc) = _group(c)
    c.post(f"/g/{code}/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b]})
    m = c.get(f"/g/{code}/api/live").json()["matches"][0]
    assert len(m["win_prob"]) == 2 and m["win_prob"][0]["pct"] + m["win_prob"][1]["pct"] == 100
    # TT gets a 3-way bar
    c.post(f"/g/{code}/api/match/start", json={"kind": "tt", "rotation": [a, b, cc]})
    tt = [x for x in c.get(f"/g/{code}/api/live").json()["matches"] if x["kind"] == "tt"][0]
    assert len(tt["win_prob"]) == 3


def test_history_date_edit(tmp_path):
    c = _c(tmp_path)
    code, (a, b, cc) = _group(c)
    mid = c.post(f"/g/{code}/api/played",
                 json={"kind": "singles", "side1": [a], "side2": [b], "sets": [[6, 4]],
                       "played_on": "2026-07-01 10:00"}).json()["id"]
    c.post(f"/g/{code}/api/match/{mid}/date", json={"played_on": "2026-07-02 15:30"})
    h = c.get(f"/g/{code}/api/history").json()["matches"][0]
    assert h["played_on"] == "2026-07-02 15:30"


def test_tt_stores_confirmed_receiver(tmp_path):
    c = _c(tmp_path)
    code, (a, b, cc) = _group(c)
    mid = c.post(f"/g/{code}/api/match/start", json={"kind": "tt", "rotation": [a, b, cc]}).json()["id"]
    c.post(f"/g/{code}/api/match/{mid}/tt", json={"server": a, "receiver": b, "winner": a})
    m = c.get(f"/g/{code}/api/match/{mid}").json()
    g = m["tt_games"][0]
    assert g["server"] == a and g["receiver"] == b and g["winner"] == a
