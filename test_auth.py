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


# --- email OTP: which token TYPE a mailed code verifies as -------------------
# The first external user's sign-in died here: a first-time email uses Supabase's "Confirm
# signup" template, whose code verifies as type 'signup', but we only ever sent type 'email'.
class _FakeHTTPError(Exception):
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        import json
        return json.dumps(self._payload).encode()


def _fake_supabase(monkeypatch, accept_type=None, error_payload=None):
    """Pretend to be Supabase /auth/v1/verify; record which types were attempted."""
    import json as _json
    import auth
    monkeypatch.setattr(auth, "AUTH_MODE", "supabase")
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(auth, "SUPABASE_ANON_KEY", "anon")
    tried = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({"access_token": "real-token"}).encode()

    def fake_urlopen(req, timeout=None):
        kind = _json.loads(req.data.decode())["type"]
        tried.append(kind)
        if accept_type and kind == accept_type:
            return _Resp()
        raise _FakeHTTPError(error_payload or {"msg": "Token has expired or is invalid"})

    monkeypatch.setattr(auth.urllib.request, "urlopen", fake_urlopen)
    return tried


def test_signup_code_verifies_even_though_we_try_email_first(monkeypatch):
    """A brand-new user's code is type 'signup'. It must still sign them in."""
    import auth
    tried = _fake_supabase(monkeypatch, accept_type="signup")
    r = auth.verify_email_otp("new@user.com", "123456")
    assert r.get("token") == "real-token", r
    assert tried[0] == "email", "returning users are the common case, so try 'email' first"
    assert "signup" in tried, "a first-time code must still be accepted"


def test_returning_user_code_takes_the_first_try(monkeypatch):
    import auth
    tried = _fake_supabase(monkeypatch, accept_type="email")
    assert auth.verify_email_otp("old@user.com", "123456").get("token") == "real-token"
    assert tried == ["email"], "no wasted round trips once the first type works"


def test_a_genuinely_bad_code_surfaces_supabase_reason(monkeypatch):
    import auth
    _fake_supabase(monkeypatch, error_payload={"msg": "Token has expired or is invalid"})
    r = auth.verify_email_otp("x@y.com", "000000")
    assert "token" not in r
    assert "expired" in r["error"].lower(), f"expired and mistyped need different fixes: {r}"


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
