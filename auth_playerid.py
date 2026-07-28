"""Player-ID sign-in (path B) + set-a-password.

Player CODES are PUBLIC — they are printed as Name#CODE on the leaderboard. That is the whole
reason this module never touches email: turning a public code into an email address would make
the leaderboard an email directory. The old implementation did exactly that (code -> auth uuid ->
Supabase Admin API -> email -> password grant) and needed a service-role key on the server to do
it. It is gone. Passwords now live here as a salted scrypt digest and nothing else.

Flow: client POSTs {player_id, password} -> code -> players.password_hash -> verify -> a
server-signed session token (auth.mint_session) that the ordinary middleware accepts, exactly
like a Google session. No email is read, stored, or returned at any point.
"""
from __future__ import annotations
import time

import auth
import db

# Wrong code and wrong password are indistinguishable to the caller.
GENERIC_401 = {"error": "code or password incorrect"}
NO_PASSWORD_MSG = ("no password set for this player — sign in with Google, "
                   "then set a password in your profile")

# A real hash to verify against when the code is unknown, so a bad code costs the same ~scrypt
# time as a bad password and cannot be told apart by timing.
_DUMMY_HASH = auth.hash_password("not-a-real-password")

# Rate limit: two independent buckets. Per-code stops one account being hammered from many IPs;
# per-IP stops one host sweeping many codes. In-memory, so it is per serverless instance — an
# attacker spread across instances gets more than the nominal 5/min.
# ponytail: in-memory buckets; move to the DB if cross-instance limiting is ever needed
_HITS: dict[str, list[float]] = {}
_WINDOW = 60           # seconds
_MAX = 5               # attempts per window per bucket


def _rate_ok(key: str, now: float) -> bool:
    hits = [t for t in _HITS.get(key, []) if now - t < _WINDOW]
    hits.append(now)
    _HITS[key] = hits
    return len(hits) <= _MAX


def _row_get(row, key):
    try:
        return row[key]
    except Exception:
        return None


def player_signin(con, code, password, ip, now=None):
    """Returns (http_status, body). Never returns an email, never says whether a code exists."""
    now = time.time() if now is None else now
    code = (code or "").strip().upper()
    if not code or not password:
        return 400, {"error": "player ID and password required"}
    # Evaluate BOTH buckets (no short-circuit) so every attempt is recorded against both.
    ok_code = _rate_ok("code:" + code, now)
    ok_ip = _rate_ok("ip:" + str(ip), now)
    if not (ok_code and ok_ip):
        return 429, {"error": "too many attempts — wait a minute"}

    row = db.player_by_code(con, code)
    if row is None:
        auth.verify_password(password, _DUMMY_HASH)      # equalise timing with the real path
        return 401, GENERIC_401
    stored = _row_get(row, "password_hash")
    if not stored:
        # Deliberate exception to the uniform error: it tells a real user how to get in, and
        # reveals only that a PUBLIC code exists — which the leaderboard already shows.
        return 403, {"error": NO_PASSWORD_MSG}
    if not auth.verify_password(password, stored):
        return 401, GENERIC_401
    if not auth.can_mint_sessions():
        return 503, {"error": "password sign-in is not configured on this server"}
    return 200, {"token": auth.mint_session(str(_row_get(row, "id"))),
                 "player_id": _row_get(row, "id")}


def do_set_password(con, auth_sub, new_password):
    """Set the signed-in caller's own password. Stores only a salted digest."""
    if len(new_password or "") < 8:
        return 400, {"error": "password must be at least 8 characters"}
    if not db.get_player(con, auth_sub):
        return 400, {"error": "set up your player first"}
    db.set_password_hash(con, auth_sub, auth.hash_password(new_password))
    return 200, {"ok": True}


def clear_password(con, pid):
    """Admin reset: drop the hash so the player can set a new one after signing in with Google."""
    db.set_password_hash(con, pid, None)
