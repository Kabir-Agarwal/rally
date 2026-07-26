"""Player-ID sign-in + set-a-password (Task 6).

Player IDs are PUBLIC (printed as Name#CODE on the leaderboard), so the client must never be able
to turn a player ID into an email — that would make the leaderboard an email directory. Therefore
the code -> email lookup happens ONLY on the server (Supabase Admin API, service-role key), and the
email is NEVER returned to the client.

Flow: client POSTs {player_id, password} (player_id = the 5-char public code) ->
  code -> players.auth_id; if players.password_set is falsy the account is Google-only (or never set
  a password) -> a specific "set a password first" message (no grant attempted) ->
  auth_id -> email (server-only) -> Supabase password grant -> return ONLY the session.
Hard per-(ip, code) rate limit. Deploy-gated on the identity migration (players.code / auth_id /
password_set), which is applied to live Postgres separately via Supabase MCP.

NEW SERVER SECRET (untracked .env only, never a tracked file, never sent to the client):
  SUPABASE_SERVICE_KEY = <service_role key>   # used only for the server-side email lookup
"""
from __future__ import annotations
import os
import json
import time
import urllib.request
import urllib.error

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or ""
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""

GOOGLE_ONLY_MSG = "this account signs in with Google — set a password first"
GENERIC_401 = {"error": "wrong player ID or password"}

# ---- hard rate limit: token bucket per (ip, code). In-memory => per serverless instance; back
#      with the DB/Redis for cross-instance limiting. Deliberately strict. ---------------------
_HITS: dict[str, list[float]] = {}
_WINDOW = 300           # seconds
_MAX = 5                # 5 attempts / 5 min / (ip+code)


def _rate_ok(key: str, now: float) -> bool:
    hits = [t for t in _HITS.get(key, []) if now - t < _WINDOW]
    hits.append(now)
    _HITS[key] = hits
    return len(hits) <= _MAX


def _row_get(row, key, idx):
    return (row[key] if hasattr(row, "keys") else row[idx])


# ---- real Supabase calls (monkeypatched in tests) --------------------------------------------
def _sb(url: str, headers: dict, body: dict | None = None, method: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception:
        return 0, {}


def email_for_auth_id(auth_id: str):
    """uuid -> email via the Supabase Admin API. Server-side ONLY; never returned to the client."""
    if not (SUPABASE_URL and SUPABASE_SERVICE_KEY):
        return None
    status, user = _sb(f"{SUPABASE_URL}/auth/v1/admin/users/{auth_id}",
                       {"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY})
    return user.get("email") if status == 200 else None


def password_grant(email: str, password: str):
    """Supabase password sign-in. Returns (ok, session_or_none)."""
    status, j = _sb(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                    {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                    {"email": email, "password": password})
    if status == 200 and j.get("access_token"):
        return True, {"access_token": j["access_token"], "refresh_token": j.get("refresh_token"),
                      "expires_in": j.get("expires_in"), "token_type": j.get("token_type", "bearer")}
    return False, None


def update_password(user_token: str, new_password: str) -> bool:
    """Set the caller's OWN password via their session (Supabase updateUser = PUT /auth/v1/user)."""
    status, _ = _sb(f"{SUPABASE_URL}/auth/v1/user",
                    {"Authorization": f"Bearer {user_token}", "apikey": SUPABASE_ANON_KEY,
                     "Content-Type": "application/json"},
                    {"password": new_password}, method="PUT")
    return status in (200, 201)


# ---- pure request logic (unit-tested; Supabase calls injected) --------------------------------
def player_signin(con, code, password, ip, now=None, email_lookup=None, grant=None):
    """Returns (http_status, body_dict). Never leaks email or whether a code exists (uniform 401)."""
    now = time.time() if now is None else now
    email_lookup = email_lookup or email_for_auth_id
    grant = grant or password_grant
    code = (code or "").strip().upper()
    if not code or not password:
        return 400, {"error": "player ID and password required"}
    if not _rate_ok(f"{ip}:{code}", now):
        return 429, {"error": "too many attempts — wait a few minutes"}
    row = con.execute("SELECT auth_id, password_set FROM players WHERE code=?", (code,)).fetchone()
    if not row:
        return 401, GENERIC_401
    auth_id = _row_get(row, "auth_id", 0)
    password_set = _row_get(row, "password_set", 1)
    if not auth_id:
        return 401, GENERIC_401
    if not password_set:
        return 409, {"error": GOOGLE_ONLY_MSG}     # Google-only: specific, actionable message
    email = email_lookup(str(auth_id))             # server-side only
    if not email:
        return 401, GENERIC_401
    ok, session = grant(email, password)
    if not ok:
        return 401, GENERIC_401
    return 200, session                            # session ONLY — no email, no code->email leak


def do_set_password(con, auth_sub, new_password, user_token, updater=None):
    """Returns (http_status, body). Flips players.password_set=1 for every row of this auth user."""
    updater = updater or update_password
    if len(new_password or "") < 8:
        return 400, {"error": "password must be at least 8 characters"}
    if not updater(user_token, new_password):
        return 400, {"error": "could not set password"}
    con.execute("UPDATE players SET password_set=1 WHERE auth_id=?", (auth_sub,))
    con.commit()
    return 200, {"ok": True}
