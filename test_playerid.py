"""Task 6 — player-ID sign-in + set-a-password. Supabase calls are injected, so these test the
security-critical logic: email is NEVER returned to the client, code existence is not leaked
(uniform 401), Google-only accounts get the specific message, and the rate limit bites.
The real Supabase password grant / admin email lookup are NOT exercised here (no service key /
live Supabase in this env) — same limitation class as the OAuth happy path."""
import sqlite3
import db
import auth_playerid as pid


def _con(code="ABCDE", auth_id="uuid-1", password_set=1):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    con.execute("INSERT INTO groups(id,name,code,created_at) VALUES(1,'G','GGG','t')")
    con.execute(
        "INSERT INTO players(id,group_id,name,created_at,code,auth_id,password_set) VALUES(1,1,'Ann','t',?,?,?)",
        (code, auth_id, password_set))
    con.commit()
    return con


def setup_function(_):
    pid._HITS.clear()                       # isolate the rate-limit bucket per test


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


def test_no_auth_id_uniform_401():
    con = _con(auth_id=None)
    st, _ = pid.player_signin(con, "ABCDE", "pw", "ip", email_lookup=OK_LOOKUP, grant=OK_GRANT)
    assert st == 401


def test_google_only_specific_message_409():
    con = _con(password_set=0)
    st, body = pid.player_signin(con, "abcde", "pw", "ip")   # lowercase normalizes to the code
    assert st == 409 and "Google" in body["error"]


def test_success_returns_session_and_never_the_email():
    con = _con()
    seen = {}
    def lookup(a): seen["auth"] = a; return "secret@example.com"
    def grant(email, pw): seen["email"] = email; return True, {"access_token": "tok", "refresh_token": "r"}
    st, body = pid.player_signin(con, "ABCDE", "pw", "ip", email_lookup=lookup, grant=grant)
    assert st == 200
    assert body["access_token"] == "tok"
    assert "email" not in body                          # email is NEVER leaked to the client
    assert seen["auth"] == "uuid-1" and seen["email"] == "secret@example.com"


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
    # a different client IP is unaffected
    assert pid.player_signin(con, "ABCDE", "x", "9.9.9.9", now=1000, email_lookup=OK_LOOKUP, grant=g)[0] == 401


def test_set_password_min_length():
    con = _con(password_set=0)
    assert pid.do_set_password(con, "uuid-1", "short", "tok", updater=lambda t, p: True)[0] == 400


def test_set_password_flips_flag_on_success():
    con = _con(password_set=0)
    st, body = pid.do_set_password(con, "uuid-1", "longenough123", "tok", updater=lambda t, p: True)
    assert st == 200 and body["ok"] is True
    assert con.execute("SELECT password_set FROM players WHERE auth_id='uuid-1'").fetchone()[0] == 1


def test_set_password_updater_failure_does_not_flip():
    con = _con(password_set=0)
    st, _ = pid.do_set_password(con, "uuid-1", "longenough123", "tok", updater=lambda t, p: False)
    assert st == 400
    assert con.execute("SELECT password_set FROM players WHERE auth_id='uuid-1'").fetchone()[0] == 0
