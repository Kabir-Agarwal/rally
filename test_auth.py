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


def test_mock_google_signin(tmp_path):
    appmod, c = _fresh(tmp_path)
    r = c.post("/api/auth/google", json={"email": "g@gmail.com"}).json()
    assert r["token"].startswith("mock.") and r["email"] == "g@gmail.com"
    assert c.get("/api/auth/config").json()["mode"] == "mock"


def test_config_reports_guest_allowed(tmp_path):
    # The client renders the guest "Continue" button only when the server says guest is allowed.
    appmod, c = _fresh(tmp_path)
    cfg = c.get("/api/auth/config").json()
    assert cfg["mode"] == "mock" and cfg["guest"] is True     # mock mode -> guest allowed
    # (in supabase mode guest is False; the endpoint guest sign-in also 400s — see test_signin)


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


def test_friend_request_accept_then_appears_in_meta(tmp_path):
    # Task 5 chain (server side): request -> shows as pending -> accept -> both see each other in the
    # court-picker roster (/api/meta). Accept/decline routes exercised.
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    assert c.post("/api/friend/request", json={"id": b}, headers=ha).json()["status"] == "pending"
    assert a in [x["id"] for x in c.get("/api/friends", headers=hb).json()["pending"]]   # b sees it
    assert a not in [p["id"] for p in c.get("/api/meta", headers=hb).json()["players"]]  # not yet a friend
    c.post("/api/friend/accept", json={"id": a}, headers=hb)                             # b accepts
    assert b in [p["id"] for p in c.get("/api/meta", headers=ha).json()["players"]]      # now in each other's picker
    assert a in [p["id"] for p in c.get("/api/meta", headers=hb).json()["players"]]


def test_friend_request_by_code_and_decline(tmp_path):
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    bcode = c.get("/api/me", headers=hb).json()["code"]
    assert c.post("/api/friend/request", json={"code": bcode}, headers=ha).status_code == 200   # request by CODE
    c.post("/api/friend/decline", json={"id": a}, headers=hb)                                    # b declines
    assert not c.get("/api/friends", headers=hb).json()["pending"]                               # request gone
    assert a not in [p["id"] for p in c.get("/api/meta", headers=hb).json()["players"]]


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


def test_player_follows_the_account_not_the_device(tmp_path):
    """P2 ('details not saved'): a player row is keyed by the AUTH USER id, not the device.

    So signing in from a different browser/phone with the same identity must land on the same
    player, and must not be able to create a second one. This is what makes the old link-based
    email flow merely confusing rather than destructive: the details were saved, just under a
    session left behind in the mail app's browser.
    """
    from fastapi.testclient import TestClient
    appmod, c = _fresh(tmp_path)
    h = _hdr("email:sam@example.com")

    assert c.get("/api/me", headers=h).json().get("needs_name") is True
    c.post("/api/me/claim", json={"name": "Sam", "real_name": "Sam R"}, headers=h)

    other_device = TestClient(appmod.app)                 # fresh browser, same identity
    me = other_device.get("/api/me", headers=h).json()
    assert me["player_name"] == "Sam"
    assert me["player_real_name"] == "Sam R"
    assert not me.get("needs_name"), "details must follow the account, not the device"

    # ...and a second claim is refused rather than silently making a duplicate player
    assert other_device.post("/api/me/claim", json={"name": "Sam2"}, headers=h).status_code == 409
