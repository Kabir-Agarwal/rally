"""Server support (new model): /api/meta roster, win-probability in /api/live, history date edit,
TT stored receiver. Uses a group so the roster = members."""
from conftest import signin


def _group(c):
    a, ha = signin(c, "a", "Ann")
    code = c.post("/api/group/create", json={"name": "G"}, headers=ha).json()["code"]
    b, hb = signin(c, "b", "Bob"); c.post("/api/group/join", json={"code": code}, headers=hb)
    d, hd = signin(c, "c", "Cara"); c.post("/api/group/join", json={"code": code}, headers=hd)
    return code, a, b, d, ha


def test_meta_shape_zero_based(app_client):
    c = app_client
    code, a, b, d, ha = _group(c)
    meta = c.get(f"/api/meta?group={code}", headers=ha).json()
    assert {"players", "pairs", "pair_provisional"} <= set(meta)
    p = meta["players"][0]
    assert {"id", "name", "live", "singles", "singles_n", "doubles", "doubles_n"} <= set(p)
    assert p["singles"] == 0 and p["singles_n"] == 0


def test_live_has_win_prob(app_client):
    c = app_client
    code, a, b, d, ha = _group(c)
    c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": code}, headers=ha)
    m = c.get(f"/api/live?group={code}", headers=ha).json()["matches"][0]
    assert len(m["win_prob"]) == 2 and m["win_prob"][0]["pct"] + m["win_prob"][1]["pct"] == 100
    e, he = signin(c, "e", "Dee"); c.post("/api/group/join", json={"code": code}, headers=he)
    f, hf = signin(c, "f", "Eff"); c.post("/api/group/join", json={"code": code}, headers=hf)
    c.post("/api/match/start", json={"kind": "tt", "rotation": [d, e, f], "group": code}, headers=ha)
    tt = [x for x in c.get(f"/api/live?group={code}", headers=ha).json()["matches"] if x["kind"] == "tt"][0]
    assert len(tt["win_prob"]) == 3


def test_history_date_edit(app_client):
    c = app_client
    code, a, b, d, ha = _group(c)
    mid = c.post("/api/played", json={"kind": "singles", "side1": [a], "side2": [b],
                 "sets": [[6, 4]], "played_on": "2026-07-01 10:00", "group": code}, headers=ha).json()["id"]
    c.post(f"/api/match/{mid}/date", json={"played_on": "2026-07-02 15:30"}, headers=ha)
    h = c.get(f"/api/history?group={code}", headers=ha).json()["matches"][0]
    assert h["played_on"] == "2026-07-02 15:30"


def test_tt_stores_confirmed_receiver(app_client):
    c = app_client
    code, a, b, d, ha = _group(c)
    mid = c.post("/api/match/start", json={"kind": "tt", "rotation": [a, b, d], "group": code}, headers=ha).json()["id"]
    c.post(f"/api/match/{mid}/tt", json={"server": a, "receiver": b, "winner": a}, headers=ha)
    g = c.get(f"/api/match/{mid}").json()["tt_games"][0]
    assert g["server"] == a and g["receiver"] == b and g["winner"] == a
