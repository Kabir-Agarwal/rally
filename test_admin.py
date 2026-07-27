"""Admin tests (new model): per-GROUP admin powers + guards (the old global god-mode of
rename/void/link/player-cascade is largely replaced by group admin_id powers). The remaining
secret-key god-mode is /admin/api/* (overview, match delete)."""
from conftest import signin, bearer


def _group(c):
    a, ha = signin(c, "a", "Ann")                      # a is the group admin
    r = c.post("/api/group/create", json={"name": "G"}, headers=ha).json()
    b, hb = signin(c, "b", "Bob")
    c.post("/api/group/join", json={"code": r["code"]}, headers=hb)   # public -> member
    return r["id"], r["code"], a, ha, b, hb


def test_group_admin_only_guards(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    # a non-admin member cannot perform admin actions
    assert c.post(f"/api/group/{gid}/rename", json={"name": "X"}, headers=hb).status_code == 403
    assert c.post(f"/api/group/{gid}/public", json={"is_public": False}, headers=hb).status_code == 403
    assert c.post(f"/api/group/{gid}/code", json={}, headers=hb).status_code == 403
    assert c.post(f"/api/group/{gid}/delete", json={}, headers=hb).status_code == 403
    assert c.get(f"/api/group/{gid}/requests", headers=hb).status_code == 403


def test_admin_can_rename_and_flip_public(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    assert c.post(f"/api/group/{gid}/rename", json={"name": "Renamed"}, headers=ha).status_code == 200
    assert c.post(f"/api/group/{gid}/public", json={"is_public": False}, headers=ha).status_code == 200
    g = [g for g in c.get("/api/groups", headers=ha).json()["groups"] if g["id"] == gid][0]
    assert g["name"] == "Renamed" and g["is_public"] is False


def test_regen_invalidates_old_code(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    new = c.post(f"/api/group/{gid}/code", json={}, headers=ha).json()["code"]
    assert new != code
    # old code no longer joins
    d, hd = signin(c, "d", "Dan")
    assert c.post("/api/group/join", json={"code": code}, headers=hd).status_code == 404


def test_hand_over_admin(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    c.post(f"/api/group/{gid}/admin", json={"player_id": b}, headers=ha)   # a hands admin to b
    # now b is admin, a is not
    assert c.post(f"/api/group/{gid}/rename", json={"name": "Z"}, headers=hb).status_code == 200
    assert c.post(f"/api/group/{gid}/rename", json={"name": "Y"}, headers=ha).status_code == 403


def test_remove_member(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    c.post(f"/api/group/{gid}/remove", json={"player_id": b}, headers=ha)
    assert gid not in [g["id"] for g in c.get("/api/groups", headers=hb).json()["groups"]]


def test_member_can_leave_admin_cannot(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)   # a = admin, b = member
    # a non-admin member leaves -> removed from the group
    assert c.post(f"/api/group/{gid}/leave", json={}, headers=hb).status_code == 200
    assert gid not in [g["id"] for g in c.get("/api/groups", headers=hb).json()["groups"]]
    # the admin cannot simply leave (would orphan the group) -> 400 with a plain reason
    r = c.post(f"/api/group/{gid}/leave", json={}, headers=ha)
    assert r.status_code == 400 and "admin" in r.json()["error"].lower()
    assert gid in [g["id"] for g in c.get("/api/groups", headers=ha).json()["groups"]]   # still in it


def test_leave_keeps_the_groups_matches(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": code},
                 headers=ha).json()["id"]
    c.post(f"/api/group/{gid}/leave", json={}, headers=hb)
    assert c.get(f"/api/match/{mid}").json()["group_id"] == gid   # match untouched by the leave


def test_delete_group_keeps_matches(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": code},
                 headers=ha).json()["id"]
    c.post(f"/api/group/{gid}/delete", json={}, headers=ha)
    m = c.get(f"/api/match/{mid}").json()
    assert m is not None and m["group_id"] is None and m["former_group_name"] == "G"


def test_private_join_request_admin_approves_and_declines(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    c.post(f"/api/group/{gid}/public", json={"is_public": False}, headers=ha)
    d, hd = signin(c, "d", "Dan"); c.post("/api/group/join", json={"code": code}, headers=hd)
    e, he = signin(c, "e", "Eve"); c.post("/api/group/join", json={"code": code}, headers=he)
    ids = [p["id"] for p in c.get(f"/api/group/{gid}/requests", headers=ha).json()["requests"]]
    assert d in ids and e in ids
    c.post(f"/api/group/{gid}/approve", json={"player_id": d}, headers=ha)
    c.post(f"/api/group/{gid}/decline", json={"player_id": e}, headers=ha)
    left = [p["id"] for p in c.get(f"/api/group/{gid}/requests", headers=ha).json()["requests"]]
    assert d not in left and e not in left
    assert gid in [g["id"] for g in c.get("/api/groups", headers=hd).json()["groups"]]      # d joined
    assert gid not in [g["id"] for g in c.get("/api/groups", headers=he).json()["groups"]]  # e declined


def test_godmode_key_gated(app_client):
    c = app_client
    key = c.app_mod.ADMIN_KEY
    assert c.get("/admin/api/overview").status_code == 404             # no key -> hidden
    r = c.get("/admin/api/overview", headers={"X-Admin-Key": key})
    assert r.status_code == 200 and {"groups", "players", "matches", "live"} <= set(r.json())


def test_godmode_match_delete(app_client):
    c = app_client
    gid, code, a, ha, b, hb = _group(c)
    mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                 headers=ha).json()["id"]
    key = c.app_mod.ADMIN_KEY
    assert c.post(f"/admin/api/match/{mid}/delete").status_code == 404   # no key
    assert c.post(f"/admin/api/match/{mid}/delete", headers={"X-Admin-Key": key}).status_code == 200
    assert c.get(f"/api/match/{mid}").json()["status"] == "deleted"
