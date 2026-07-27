"""Player-ID sign-in (Task 6) reconciled to the CLEAN-FOUNDATION schema: players.id IS the auth
user id and there is no auth_id/password_set column. Supabase calls are injected, so these test the
security-critical logic: email is NEVER returned to the client, code existence is not leaked
(uniform 401), and the rate limit bites. The real Supabase password grant / admin email lookup are
NOT exercised here (no service key / live Supabase in this env)."""
import sqlite3
import db
import auth_playerid as pid


def _con(code="ABCDE", pid_id="00000000-0000-0000-0000-000000000001"):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    con.execute("INSERT INTO players(id, code, game_name, created_at) VALUES(?,?,?, 't')",
                (pid_id, code, "Ann"))
    con.commit()
    return con


def setup_function(_):
    pid._HITS.clear()


OK_GRANT = lambda e, p: (True, {"access_token": "tok", "refresh_token": "r"})
OK_LOOKUP = lambda a: "secret@example.com"


def test_missing_fields_400():
    con = _con()
    assert pid.player_signin(con, "", "x", "ip")[0] == 400
    assert pid.player_signin(con, "ABCDE", "", "ip")[0] == 400


def test_unknown_code_uniform_401():
    con = _con()
    st, body = pid.player_signin(con, "ZZZZZ", "pw", "ip", email_lookup=OK_LOOKUP, grant=OK_GRANT)
    assert st == 401 and body == pid.GENERIC_401


def test_success_returns_session_and_never_the_email():
    con = _con()
    seen = {}
    def lookup(a): seen["auth"] = a; return "secret@example.com"
    def grant(email, pw): seen["email"] = email; return True, {"access_token": "tok", "refresh_token": "r"}
    st, body = pid.player_signin(con, "abcde", "pw", "ip", email_lookup=lookup, grant=grant)  # lowercase normalizes
    assert st == 200
    assert body["access_token"] == "tok"
    assert "email" not in body                          # email is NEVER leaked to the client
    assert seen["auth"] == "00000000-0000-0000-0000-000000000001"
    assert seen["email"] == "secret@example.com"


def test_wrong_password_uniform_401():
    con = _con()
    st, body = pid.player_signin(con, "ABCDE", "bad", "ip", email_lookup=OK_LOOKUP, grant=lambda e, p: (False, None))
    assert st == 401 and body == pid.GENERIC_401


def test_rate_limit_per_ip_and_code():
    con = _con()
    g = lambda e, p: (False, None)
    for _ in range(5):
        assert pid.player_signin(con, "ABCDE", "x", "1.2.3.4", now=1000, email_lookup=OK_LOOKUP, grant=g)[0] == 401
    assert pid.player_signin(con, "ABCDE", "x", "1.2.3.4", now=1000, email_lookup=OK_LOOKUP, grant=g)[0] == 429
    assert pid.player_signin(con, "ABCDE", "x", "9.9.9.9", now=1000, email_lookup=OK_LOOKUP, grant=g)[0] == 401


def test_set_password_min_length():
    con = _con()
    assert pid.do_set_password(con, "sub", "short", "tok", updater=lambda t, p: True)[0] == 400


def test_set_password_success():
    con = _con()
    st, body = pid.do_set_password(con, "sub", "longenough123", "tok", updater=lambda t, p: True)
    assert st == 200 and body["ok"] is True


def test_set_password_updater_failure():
    con = _con()
    assert pid.do_set_password(con, "sub", "longenough123", "tok", updater=lambda t, p: False)[0] == 400
