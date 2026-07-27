"""Auth (new model): writes require sign-in; reads open; mock OTP/Google; global self-serve
identity (no admin-added players, no per-group links); friends-only court picker."""
from conftest import _fresh_app, bearer, signin


def _fresh(tmp_path):
    from fastapi.testclient import TestClient
    appmod = _fresh_app(tmp_path)
    return appmod, TestClient(appmod.app)


def _hdr(sub="user-a"):
    return {"Authorization": bearer(sub)}


def test_write_requires_signin_read_is_open(tmp_path):
    appmod, c = _fresh(tmp_path)
    assert c.post("/api/group/create", json={"name": "G"}).status_code == 401   # no token
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    body = {"kind": "singles", "side1": [a], "side2": [b], "group": None}
    assert c.post("/api/match/start", json=body).status_code == 401             # no token
    assert c.post("/api/match/start", json=body, headers=ha).status_code == 200
    assert c.get("/api/live").status_code == 200                                # reads open
    assert c.get("/api/leaderboard?mode=singles").status_code == 200


def test_bad_token_rejected(tmp_path):
    appmod, c = _fresh(tmp_path)
    r = c.post("/api/group/create", json={"name": "G"}, headers={"Authorization": "Bearer mock.bad.sig"})
    assert r.status_code == 401


def test_mock_email_otp_flow(tmp_path):
    appmod, c = _fresh(tmp_path)
    start = c.post("/api/auth/email/start", json={"email": "x@y.com"}).json()
    assert start["sent"] and "dev_code" in start
    assert c.post("/api/auth/email/verify", json={"email": "x@y.com", "code": "000000"}).status_code == 401
    ok = c.post("/api/auth/email/verify", json={"email": "x@y.com", "code": start["dev_code"]})
    assert ok.status_code == 200 and ok.json()["token"].startswith("mock.")


def test_mock_google_signin(tmp_path):
    appmod, c = _fresh(tmp_path)
    r = c.post("/api/auth/google", json={"email": "g@gmail.com"}).json()
    assert r["token"].startswith("mock.") and r["email"] == "g@gmail.com"
    assert c.get("/api/auth/config").json()["mode"] == "mock"


def test_first_signin_self_creates_player_with_code(tmp_path):
    # NEW model: no admin-added players — a signed-in user with no player gets needs_name, then
    # /api/me/claim creates a GLOBAL player with a permanent code.
    appmod, c = _fresh(tmp_path)
    h = _hdr("u1")
    assert c.get("/api/me", headers=h).json()["needs_name"] is True
    r = c.post("/api/me/claim", json={"name": "Ann"}, headers=h).json()
    assert len(r["code"]) == 5
    me = c.get("/api/me", headers=h).json()
    assert me["player_id"] and me["player_name"] == "Ann"
    # re-claim is rejected (identity already has a player) — not asked again
    assert c.post("/api/me/claim", json={"name": "Other"}, headers=h).status_code == 409


def test_identity_is_the_token_stable_across_devices(tmp_path):
    appmod, c = _fresh(tmp_path)
    h = _hdr("same-sub")
    c.post("/api/me/claim", json={"name": "Sam"}, headers=h)
    pid1 = c.get("/api/me", headers=h).json()["player_id"]
    # a "different device" with the same auth sub resolves to the same player
    pid2 = c.get("/api/me", headers={"Authorization": bearer("same-sub")}).json()["player_id"]
    assert pid1 == pid2


def test_picker_always_includes_self_even_with_zero_friends(tmp_path):
    # Task 4: with no friends, /api/meta offers exactly one placeable chip — you.
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "solo", "Solo")
    players = c.get("/api/meta", headers=ha).json()["players"]
    assert len(players) == 1 and players[0]["id"] == a


def test_court_picker_reads_accepted_friends_only(tmp_path):
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")      # will be an accepted friend
    d, hd = signin(c, "d", "Dan")      # will be pending only
    c.post("/api/friend/request", json={"id": b}, headers=ha)
    c.post("/api/friend/request", json={"id": a}, headers=hb)   # reciprocal -> accepted
    c.post("/api/friend/request", json={"id": d}, headers=ha)   # pending (Dan hasn't accepted)
    names = [p["name"] for p in c.get("/api/meta", headers=ha).json()["players"]]
    assert "Ann" in names and "Bob" in names       # self + accepted friend
    assert "Dan" not in names                        # pending is NOT in the picker
