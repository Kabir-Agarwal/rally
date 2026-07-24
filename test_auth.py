"""Task 4: auth gating, mock OTP/Google, identity->player linking, admin-only players."""
import importlib
import db as dbmod


def _fresh(tmp_path):
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    from fastapi.testclient import TestClient
    return appmod, TestClient(appmod.app)


def _signed_in(appmod, sub="user-a", email="a@test"):
    return {"Authorization": "Bearer " + appmod.auth.mint_mock_token(sub, email)}


def _admin(appmod):
    return {"X-Admin-Key": appmod.ADMIN_KEY}


# ---- writes require sign-in; reads don't ----
def test_write_requires_signin_read_is_open(tmp_path):
    appmod, c = _fresh(tmp_path)
    # create group without a token -> 401
    assert c.post("/api/group/create", json={"name": "G"}).status_code == 401
    # signed in -> ok
    code = c.post("/api/group/create", json={"name": "G"}, headers=_signed_in(appmod)).json()["code"]
    # admin adds two players
    a = c.post(f"/g/{code}/api/player", json={"name": "Ann"}, headers=_admin(appmod)).json()["id"]
    b = c.post(f"/g/{code}/api/player", json={"name": "Bob"}, headers=_admin(appmod)).json()["id"]
    # starting a match without a token -> 401
    body = {"kind": "singles", "side1": [a], "side2": [b]}
    assert c.post(f"/g/{code}/api/match/start", json=body).status_code == 401
    # with token -> ok
    assert c.post(f"/g/{code}/api/match/start", json=body, headers=_signed_in(appmod)).status_code == 200
    # reads are open (no token)
    assert c.get(f"/g/{code}/api/live").status_code == 200
    assert c.get(f"/g/{code}/api/leaderboard?scope=group&mode=singles").status_code == 200


def test_bad_token_rejected(tmp_path):
    appmod, c = _fresh(tmp_path)
    r = c.post("/api/group/create", json={"name": "G"}, headers={"Authorization": "Bearer mock.bad.sig"})
    assert r.status_code == 401


# ---- mock sign-in flows ----
def test_mock_email_otp_flow(tmp_path):
    appmod, c = _fresh(tmp_path)
    start = c.post("/api/auth/email/start", json={"email": "x@y.com"}).json()
    assert start["sent"] and "dev_code" in start
    bad = c.post("/api/auth/email/verify", json={"email": "x@y.com", "code": "000000"})
    assert bad.status_code == 401
    ok = c.post("/api/auth/email/verify", json={"email": "x@y.com", "code": start["dev_code"]})
    assert ok.status_code == 200 and ok.json()["token"].startswith("mock.")


def test_mock_google_signin(tmp_path):
    appmod, c = _fresh(tmp_path)
    r = c.post("/api/auth/google", json={"email": "g@gmail.com"}).json()
    assert r["token"].startswith("mock.") and r["email"] == "g@gmail.com"
    assert c.get("/api/auth/config").json()["mode"] == "mock"


# ---- players are admin-only ----
def test_player_creation_is_admin_only(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = c.post("/api/group/create", json={"name": "G"}, headers=_signed_in(appmod)).json()["code"]
    # signed-in member (no admin key) cannot add players
    r = c.post(f"/g/{code}/api/player", json={"name": "Ann"}, headers=_signed_in(appmod))
    assert r.status_code == 403 and "admin" in r.json()["error"].lower()
    # admin can
    assert c.post(f"/g/{code}/api/player", json={"name": "Ann"}, headers=_admin(appmod)).status_code == 200


# ---- identity <-> player link, locked, follows identity ----
def test_link_pick_once_locked_and_follows_identity(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = c.post("/api/group/create", json={"name": "G"}, headers=_signed_in(appmod)).json()["code"]
    a = c.post(f"/g/{code}/api/player", json={"name": "Ann"}, headers=_admin(appmod)).json()["id"]
    b = c.post(f"/g/{code}/api/player", json={"name": "Bob"}, headers=_admin(appmod)).json()["id"]
    me1 = _signed_in(appmod, "user-1", "1@test")
    # before linking
    assert c.get(f"/g/{code}/api/me", headers=me1).json()["player_id"] is None
    # pick Ann
    assert c.post(f"/g/{code}/api/link", json={"player_id": a}, headers=me1).status_code == 200
    assert c.get(f"/g/{code}/api/me", headers=me1).json()["player_id"] == a
    # locked: can't relink to Bob
    assert c.post(f"/g/{code}/api/link", json={"player_id": b}, headers=me1).status_code == 409
    # same identity on a "different device" (same token sub) still resolves to Ann
    assert c.get(f"/g/{code}/api/me", headers=me1).json()["player_name"] == "Ann"


def test_admin_relink(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = c.post("/api/group/create", json={"name": "G"}, headers=_signed_in(appmod)).json()["code"]
    gid = c.get("/admin/api/dashboard", headers=_admin(appmod)).json()["groups"][0]["id"]
    a = c.post(f"/g/{code}/api/player", json={"name": "Ann"}, headers=_admin(appmod)).json()["id"]
    b = c.post(f"/g/{code}/api/player", json={"name": "Bob"}, headers=_admin(appmod)).json()["id"]
    me = _signed_in(appmod, "user-9", "9@test")
    c.post(f"/g/{code}/api/link", json={"player_id": a}, headers=me)
    # admin relinks that identity to Bob (overrides the lock)
    r = c.post(f"/admin/api/group/{gid}/link",
               json={"auth_sub": "user-9", "player_id": b}, headers=_admin(appmod))
    assert r.status_code == 200
    assert c.get(f"/g/{code}/api/me", headers=me).json()["player_id"] == b
    # and can unlink
    c.post(f"/admin/api/group/{gid}/unlink", json={"auth_sub": "user-9"}, headers=_admin(appmod))
    assert c.get(f"/g/{code}/api/me", headers=me).json()["player_id"] is None
