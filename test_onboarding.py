"""Onboarding (new model): sign-in first, self-serve GLOBAL name, reuse across sign-ins,
write-gating, and the group join model (public = instant, private = admin-approved request).
The old private-name-hiding / admin-added-players / per-group claim-link are gone; these assert
the new behavior."""
from conftest import bearer, signin


def _hdr(sub="user-a"):
    return {"Authorization": bearer(sub)}


def test_spa_served_signed_out(app_client):
    # `/` and /g/<code>/live serve the SPA (a filter); no group gate, no per-group name leak logic.
    c = app_client
    a, ha = signin(c, "a", "Ann")
    code = c.post("/api/group/create", json={"name": "Club"}, headers=ha).json()["code"]
    assert c.get("/").status_code == 200
    assert c.get(f"/g/{code}/live").status_code == 200
    assert c.get("/api/me").json()["signed_in"] is False       # no token -> signed out


def test_write_rejected_without_session(app_client):
    c = app_client
    assert c.post("/api/me/claim", json={"name": "Sam"}).status_code == 401


def test_choose_name_creates_player(app_client):
    c = app_client
    me = _hdr("u1")
    r = c.post("/api/me/claim", json={"name": "Sam"}, headers=me)
    assert r.status_code == 200
    who = c.get("/api/me", headers=me).json()
    assert who["player_id"] == r.json()["player_id"] and who["player_name"] == "Sam"


def test_empty_name_rejected_duplicate_allowed_globally(app_client):
    c = app_client
    c.post("/api/me/claim", json={"name": "Sam"}, headers=_hdr("u1"))
    assert c.post("/api/me/claim", json={"name": "  "}, headers=_hdr("u2")).status_code == 400
    assert c.post("/api/me/claim", json={"name": "sam"}, headers=_hdr("u3")).status_code == 200  # global dup ok


def test_second_signin_reuses_same_player(app_client):
    c = app_client
    me = _hdr("u1")
    first = c.post("/api/me/claim", json={"name": "Sam"}, headers=me).json()["player_id"]
    assert c.get("/api/me", headers=me).json()["player_id"] == first
    assert c.post("/api/me/claim", json={"name": "Other"}, headers=me).status_code == 409  # not re-asked


def test_public_group_join_is_instant(app_client):
    c = app_client
    a, ha = signin(c, "a", "Ann")
    code = c.post("/api/group/create", json={"name": "Open"}, headers=ha).json()["code"]  # public by default
    b, hb = signin(c, "b", "Bob")
    r = c.post("/api/group/join", json={"code": code}, headers=hb).json()
    assert r["joined"] is True
    assert code in [g["code"] for g in c.get("/api/groups", headers=hb).json()["groups"]]


def test_private_group_join_queues_a_request(app_client):
    c = app_client
    a, ha = signin(c, "a", "Ann")
    gid = c.post("/api/group/create", json={"name": "Closed"}, headers=ha).json()["id"]
    code = c.post("/api/group/join", json={"code": "X"}, headers=ha)  # noop; get code below
    code = [g["code"] for g in c.get("/api/groups", headers=ha).json()["groups"]][0]
    c.post(f"/api/group/{gid}/public", json={"is_public": False}, headers=ha)  # make private
    b, hb = signin(c, "b", "Bob")
    r = c.post("/api/group/join", json={"code": code}, headers=hb).json()
    assert r.get("requested") is True and r.get("joined") is False
    reqs = c.get(f"/api/group/{gid}/requests", headers=ha).json()["requests"]
    assert b in [p["id"] for p in reqs]                          # queued for the admin
    c.post(f"/api/group/{gid}/approve", json={"player_id": b}, headers=ha)   # admin approves
    assert code in [g["code"] for g in c.get("/api/groups", headers=hb).json()["groups"]]
