"""Player CODE + password sign-in (path B).

These run on SQLite. The only backend-specific piece is the `password_hash` column, which is
mirrored in db.SCHEMA (SQLite) and applied to live Postgres by the add_players_password_hash
migration — the drift guard in db.REQUIRED fails loudly if either is missing.
"""
import pytest

import auth
import auth_playerid
from conftest import _fresh_app, bearer

PW = "correct-horse-8"


@pytest.fixture
def c(tmp_path):
    from fastapi.testclient import TestClient
    auth_playerid._HITS.clear()          # rate-limit buckets are module state
    appmod = _fresh_app(tmp_path)
    client = TestClient(appmod.app)
    client.appmod = appmod
    return client


def _player_with_password(c, sub="p1", name="Ann", pw=PW):
    h = {"Authorization": bearer(sub)}
    c.post("/api/me/claim", json={"name": name}, headers=h)
    code = c.get("/api/me", headers=h).json()["code"]
    assert c.post("/api/auth/set-password", json={"password": pw}, headers=h).status_code == 200
    return code, h


# --- storage --------------------------------------------------------------
def test_password_is_never_stored_in_plaintext(c, tmp_path):
    code, _ = _player_with_password(c)
    con = c.appmod.db.connect(tmp_path / "t.db")
    row = con.execute("SELECT password_hash FROM players WHERE code=?", (code,)).fetchone()
    stored = row["password_hash"]
    con.close()
    assert stored, "a hash should have been written"
    assert PW not in stored, "PLAINTEXT PASSWORD IN THE DATABASE"
    assert stored.startswith("scrypt$"), stored
    assert auth.verify_password(PW, stored)
    assert not auth.verify_password("wrong-password-9", stored)


def test_the_same_password_hashes_differently_each_time(c):
    """Salted: two players with the same password must not share a hash."""
    a = auth.hash_password(PW)
    b = auth.hash_password(PW)
    assert a != b, "unsalted hashing — identical passwords produced identical digests"
    assert auth.verify_password(PW, a) and auth.verify_password(PW, b)


def test_short_passwords_are_refused(c):
    h = {"Authorization": bearer("p9")}
    c.post("/api/me/claim", json={"name": "Nine"}, headers=h)
    r = c.post("/api/auth/set-password", json={"password": "short7!"}, headers=h)
    assert r.status_code == 400 and "8 characters" in r.json()["error"]


def test_set_password_requires_a_session(c):
    assert c.post("/api/auth/set-password", json={"password": PW}).status_code == 401


# --- sign-in --------------------------------------------------------------
def test_password_session_passes_the_same_middleware_as_google(c):
    """The whole point: the minted token is an ordinary session everywhere downstream."""
    code, _ = _player_with_password(c)
    r = c.post("/api/auth/player-id", json={"player_id": code, "password": PW})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert tok.startswith("rally."), "should be our own signed session, not a Supabase token"

    hp = {"Authorization": "Bearer " + tok}
    me = c.get("/api/me", headers=hp).json()
    assert me["signed_in"] and me["code"] == code
    # ...and it authorises a WRITE, which is what actually exercises the auth middleware.
    assert c.post("/api/group/create", json={"name": "From password session"}, headers=hp).status_code == 200


def test_code_is_case_insensitive(c):
    code, _ = _player_with_password(c)
    assert c.post("/api/auth/player-id",
                  json={"player_id": code.lower(), "password": PW}).status_code == 200


def test_wrong_code_and_wrong_password_are_indistinguishable(c):
    code, _ = _player_with_password(c)
    bad_pw = c.post("/api/auth/player-id", json={"player_id": code, "password": "not-the-one"})
    auth_playerid._HITS.clear()
    bad_code = c.post("/api/auth/player-id", json={"player_id": "ZZZZZ", "password": PW})
    assert bad_pw.status_code == bad_code.status_code == 401
    assert bad_pw.json() == bad_code.json(), "the two answers must be identical — no code oracle"
    assert "code or password incorrect" in bad_pw.json()["error"]


def test_player_without_a_password_is_told_to_use_google(c):
    h = {"Authorization": bearer("p2")}
    c.post("/api/me/claim", json={"name": "Bob"}, headers=h)
    code = c.get("/api/me", headers=h).json()["code"]
    r = c.post("/api/auth/player-id", json={"player_id": code, "password": PW})
    assert r.status_code == 403
    assert "Google" in r.json()["error"] and "set a password" in r.json()["error"]


def test_rate_limit_fires(c):
    code, _ = _player_with_password(c)
    codes = [c.post("/api/auth/player-id", json={"player_id": code, "password": "nope-nope-1"}).status_code
             for _ in range(7)]
    assert 429 in codes, f"rate limit never fired: {codes}"
    assert codes.index(429) <= 5, f"limit should bite by the 6th attempt: {codes}"
    # A 429 must not be bypassable by then supplying the RIGHT password.
    assert c.post("/api/auth/player-id", json={"player_id": code, "password": PW}).status_code == 429


def test_rate_limit_counts_per_code_across_ips(c):
    """Per-code bucket: hammering one account from many IPs still trips."""
    code, _ = _player_with_password(c)
    seen = []
    for i in range(7):
        seen.append(c.post("/api/auth/player-id", json={"player_id": code, "password": "nope-nope-1"},
                           headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code)
    assert 429 in seen, f"per-code limiting missing, rotating IPs got through: {seen}"


def test_signin_never_returns_an_email(c):
    code, _ = _player_with_password(c)
    body = c.post("/api/auth/player-id", json={"player_id": code, "password": PW}).json()
    assert "email" not in json_lower(body), f"code -> email leak: {body}"


def json_lower(d):
    return {str(k).lower(): v for k, v in d.items()}


# --- admin reset (Task 3) -------------------------------------------------
def test_admin_reset_clears_the_password(c, tmp_path):
    code, h = _player_with_password(c)
    pid = c.get("/api/me", headers=h).json()["player_id"]
    key = c.appmod.app_admin_key if hasattr(c.appmod, "app_admin_key") else c.appmod.ADMIN_KEY

    r = c.post(f"/admin/api/player/{pid}/reset-password", headers={"x-admin-key": key})
    assert r.status_code == 200, r.text

    # password no longer works; the player is told to go via Google again
    after = c.post("/api/auth/player-id", json={"player_id": code, "password": PW})
    assert after.status_code == 403 and "Google" in after.json()["error"]

    # and the reset is in the admin log like every other admin action
    con = c.appmod.db.connect(tmp_path / "t.db")
    actions = [r["action"] for r in con.execute("SELECT action FROM admin_log").fetchall()]
    con.close()
    assert any("reset" in a for a in actions), actions


def test_admin_reset_needs_the_admin_key(c):
    code, h = _player_with_password(c)
    pid = c.get("/api/me", headers=h).json()["player_id"]
    assert c.post(f"/admin/api/player/{pid}/reset-password").status_code == 404
    assert c.post(f"/admin/api/player/{pid}/reset-password",
                  headers={"x-admin-key": "wrong"}).status_code == 404


def test_missing_fields_are_a_400_not_a_401(c):
    """A blank form is a client mistake, not a failed credential — and must not burn rate limit."""
    for body in ({}, {"player_id": "ABCDE"}, {"password": PW}):
        r = c.post("/api/auth/player-id", json=body)
        assert r.status_code == 400, (body, r.status_code)
        assert "required" in r.json()["error"]
