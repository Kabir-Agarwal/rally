"""Admin god-mode tests: auth, bypass, cascades, code regen, admin_log."""
import importlib
import db as dbmod


def client(tmp_path):
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    from fastapi.testclient import TestClient
    c = TestClient(appmod.app)
    c.headers.update({"Authorization": "Bearer " + appmod.auth.mint_mock_token("u1", "u1@test"),
                      "X-Admin-Key": appmod.ADMIN_KEY})
    return c, appmod.ADMIN_KEY


def H(key):
    return {"X-Admin-Key": key}


def make_group(c, key, name="G"):
    return c.post("/admin/api/group/create", json={"name": name}, headers=H(key)).json()["code"]


def add(c, code, name):
    return c.post(f"/g/{code}/api/player", json={"name": name}).json()["id"]


def finished_singles(c, code, a, b, sets=[[6, 4]]):
    mid = c.post(f"/g/{code}/api/match/start",
                 json={"kind": "singles", "side1": [a], "side2": [b], "logger": a}).json()["id"]
    c.post(f"/g/{code}/api/match/{mid}/sets", json={"sets": sets})
    c.post(f"/g/{code}/api/match/{mid}/finish", json={})   # v2: immediate finished + rated
    return mid


# ---- auth ----
def test_admin_auth_enforced_on_every_endpoint(tmp_path):
    c, key = client(tmp_path)
    c.headers.pop("X-Admin-Key", None)     # this test drives the no-key / wrong-key paths
    endpoints = [
        ("get", "/admin/api/dashboard"),
        ("get", "/admin/api/group/1"),
        ("post", "/admin/api/group/create"),
        ("post", "/admin/api/group/1/public"),
        ("post", "/admin/api/group/1/regen"),
        ("post", "/admin/api/group/1/rename"),
        ("post", "/admin/api/group/1/delete"),
        ("post", "/admin/api/player/1/rename"),
        ("post", "/admin/api/player/1/delete"),
        ("post", "/admin/api/match/1/edit"),
        ("post", "/admin/api/match/1/delete"),
        ("post", "/admin/api/match/1/void"),
        ("post", "/admin/api/match/1/unvoid"),
        ("post", "/admin/api/match/1/restore"),
    ]
    for method, url in endpoints:
        kw = {"json": {}} if method == "post" else {}
        r = getattr(c, method)(url, **kw)                   # no key
        assert r.status_code == 404, f"{url} unguarded (no key)"
        r = getattr(c, method)(url, headers=H("WRONG-KEY"), **kw)
        assert r.status_code == 404, f"{url} accepted wrong key"


def test_wrong_key_generic_not_found(tmp_path):
    c, key = client(tmp_path)
    r = c.get("/admin/api/dashboard", headers=H("nope"))
    assert r.status_code == 404
    # correct key works
    assert c.get("/admin/api/dashboard", headers=H(key)).status_code == 200


# ---- v2: immediate results, admin void/unvoid + delete/restore, all rebuild ----
def test_finish_is_immediate_no_approval(tmp_path):
    c, key = client(tmp_path)
    code = make_group(c, key, "FF")
    a, b = add(c, code, "Ann"), add(c, code, "Bob")
    mid = c.post(f"/g/{code}/api/match/start",
                 json={"kind": "singles", "side1": [a], "side2": [b], "logger": a}).json()["id"]
    c.post(f"/g/{code}/api/match/{mid}/sets", json={"sets": [[6, 0]]})
    r = c.post(f"/g/{code}/api/match/{mid}/finish", json={}).json()
    assert r["status"] == "finished"                       # immediate, no pending state
    lb = c.get(f"/g/{code}/api/leaderboard?scope=group&mode=singles").json()
    assert [x for x in lb["provisional"] if x["name"] == "Ann"][0]["rating"] > 1200


def test_admin_void_unvoid_recompute(tmp_path):
    c, key = client(tmp_path)
    code = make_group(c, key, "VOID")
    a, b = add(c, code, "Ann"), add(c, code, "Bob")
    mid = finished_singles(c, code, a, b, [[6, 0]])
    def ann_rating():
        lb = c.get(f"/g/{code}/api/leaderboard?scope=group&mode=singles").json()
        return [x for x in lb["provisional"] if x["name"] == "Ann"][0]["rating"]
    assert ann_rating() > 1200
    assert c.post(f"/admin/api/match/{mid}/void", json={}, headers=H(key)).status_code == 200
    assert ann_rating() == 1200                            # voided excluded from recompute
    c.post(f"/admin/api/match/{mid}/unvoid", json={}, headers=H(key))
    assert ann_rating() > 1200                             # unvoid brings it back


def test_admin_delete_then_restore_recompute(tmp_path):
    c, key = client(tmp_path)
    code = make_group(c, key, "DEL")
    a, b = add(c, code, "Ann"), add(c, code, "Bob")
    mid = finished_singles(c, code, a, b, [[6, 0]])
    def ann_rating():
        lb = c.get(f"/g/{code}/api/leaderboard?scope=group&mode=singles").json()
        return [x for x in lb["provisional"] if x["name"] == "Ann"][0]["rating"]
    assert ann_rating() > 1200
    # admin soft-delete -> excluded; then restore -> back
    assert c.post(f"/admin/api/match/{mid}/delete", json={}, headers=H(key)).status_code == 200
    assert ann_rating() == 1200
    assert c.post(f"/admin/api/match/{mid}/restore", json={}, headers=H(key)).status_code == 200
    assert ann_rating() > 1200


# ---- cascades touch only their target ----
def test_group_delete_cascade_only_target(tmp_path):
    c, key = client(tmp_path)
    a_code = make_group(c, key, "Alpha")
    b_code = make_group(c, key, "Beta")
    aa, ab = add(c, a_code, "A1"), add(c, a_code, "A2")
    finished_singles(c, a_code, aa, ab)
    ba, bb = add(c, b_code, "B1"), add(c, b_code, "B2")
    finished_singles(c, b_code, ba, bb)
    # delete Alpha (typed-name confirm)
    gid = [g for g in c.get("/admin/api/dashboard", headers=H(key)).json()["groups"]
           if g["name"] == "Alpha"][0]["id"]
    bad = c.post(f"/admin/api/group/{gid}/delete", json={"confirm": "wrong"}, headers=H(key))
    assert bad.status_code == 400                          # confirm must match
    ok = c.post(f"/admin/api/group/{gid}/delete", json={"confirm": "Alpha"}, headers=H(key))
    assert ok.status_code == 200
    # Alpha gone, Beta intact
    assert c.get(f"/g/{a_code}/api/live").status_code == 404
    assert c.get(f"/g/{b_code}/api/live").status_code == 200
    dash = c.get("/admin/api/dashboard", headers=H(key)).json()
    beta = [g for g in dash["groups"] if g["name"] == "Beta"][0]
    assert beta["players"] == 2 and beta["matches"] == 1


def test_player_delete_cascades_only_their_matches(tmp_path):
    c, key = client(tmp_path)
    code = make_group(c, key, "P")
    a, b, cc = add(c, code, "Ann"), add(c, code, "Bob"), add(c, code, "Cara")
    m_ab = finished_singles(c, code, a, b)     # Ann vs Bob
    m_bc = finished_singles(c, code, b, cc)    # Bob vs Cara
    # delete Ann -> her match (Ann vs Bob) gone; Bob vs Cara stays; Bob & Cara stay
    r = c.post(f"/admin/api/player/{a}/delete", json={"confirm": "Ann"}, headers=H(key))
    assert r.status_code == 200
    detail = c.get(f"/admin/api/group/"
                   f"{[g for g in c.get('/admin/api/dashboard', headers=H(key)).json()['groups'] if g['name']=='P'][0]['id']}",
                   headers=H(key)).json()
    names = [p["name"] for p in detail["players"]]
    assert "Ann" not in names and "Bob" in names and "Cara" in names
    assert len(detail["matches"]) == 1                      # only Bob vs Cara remains


# ---- code regen invalidates old ----
def test_regen_invalidates_old_code(tmp_path):
    c, key = client(tmp_path)
    code = make_group(c, key, "R")
    assert c.get(f"/g/{code}/api/live").status_code == 200
    gid = c.get("/admin/api/dashboard", headers=H(key)).json()["groups"][0]["id"]
    new = c.post(f"/admin/api/group/{gid}/regen", json={}, headers=H(key)).json()["code"]
    assert new != code
    assert c.get(f"/g/{code}/api/live").status_code == 404  # old dead
    assert c.get(f"/g/{new}/api/live").status_code == 200    # new lives


# ---- admin_log written per action ----
def test_admin_log_written_per_action(tmp_path):
    c, key = client(tmp_path)
    code = make_group(c, key, "L")
    gid = c.get("/admin/api/dashboard", headers=H(key)).json()["groups"][0]["id"]
    c.post(f"/admin/api/group/{gid}/rename", json={"name": "L2"}, headers=H(key))
    log = c.get("/admin/api/dashboard", headers=H(key)).json()["log"]
    actions = [r["action"] for r in log]
    assert "group.create" in actions and "group.rename" in actions


# ---- member delete is immediate; admin sees it as deleted and can restore ----
def test_member_delete_immediate_then_admin_restore(tmp_path):
    c, key = client(tmp_path)
    code = make_group(c, key, "DR")
    a, b = add(c, code, "Ann"), add(c, code, "Bob")
    mid = finished_singles(c, code, a, b)
    gid = [g for g in c.get('/admin/api/dashboard', headers=H(key)).json()['groups'] if g['name'] == 'DR'][0]['id']
    # a member deletes the finished match -> gone from history immediately
    c.post(f"/g/{code}/api/match/{mid}/delete", json={})
    assert c.get(f"/g/{code}/api/history").json()["matches"] == []
    # admin still sees it (flagged deleted) and restores it
    detail = c.get(f"/admin/api/group/{gid}", headers=H(key)).json()
    assert detail["matches"][0]["deleted"] is True
    c.post(f"/admin/api/match/{mid}/restore", json={}, headers=H(key))
    assert len(c.get(f"/g/{code}/api/history").json()["matches"]) == 1
