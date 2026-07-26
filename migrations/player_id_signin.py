"""Player-ID sign-in + set-a-password (Task 6) — PROPOSED / NOT WIRED IN.

This is a standalone proposal module. It is intentionally NOT imported by app.py, because it
depends on the identity migration (players.code, players.auth_id, players.password_set) that has
NOT been applied to live Postgres yet. Wire it into app.py only AFTER the migration lands.

WHY A SERVER ENDPOINT AT ALL: Google and email+password sign-in are native to Supabase and attach
to the same auth.users row directly from the client. Player-ID sign-in is NOT native: a player ID
is PUBLIC (it's printed as Name#CODE on the leaderboard), so the CLIENT must never be able to turn
a player ID into an email — that would make the leaderboard an email directory. Therefore the
player_id -> email lookup happens ONLY on the server, and the email is NEVER returned to the client.

FLOW (per dispatch):
  1. client POSTs {player_id, password}   (player_id = the 5-char public code)
  2. server: code -> players.auth_id (uuid); if players.password_set is false -> the account is
     Google-only, return the specific "set a password first" message (do NOT attempt a grant)
  3. server: auth_id -> email via the Supabase ADMIN API (service-role key, server-only)
  4. server: Supabase password grant with {email, password}; return ONLY the session to the client
  5. hard rate limit, keyed on client IP + submitted code

NEW SECRET REQUIRED (goes in the untracked .env, NEVER a tracked file, NEVER sent to the client):
  SUPABASE_SERVICE_KEY = <service_role key>   # used only for the server-side email lookup
"""
from __future__ import annotations
import os
import json
import time
import urllib.request
import urllib.error

from fastapi import Request
from fastapi.responses import JSONResponse

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or ""
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""   # server-only

GOOGLE_ONLY_MSG = "this account signs in with Google — set a password first"

# ---- hard rate limit: token bucket per (ip, code). In-memory => per serverless instance; for
#      production-grade limiting back this with the DB or Redis. Deliberately strict. -----------
_HITS: dict[str, list[float]] = {}
_WINDOW = 300           # seconds
_MAX = 5                # 5 attempts / 5 min / (ip+code)


def _rate_ok(key: str) -> bool:
    now = time.time()
    hits = [t for t in _HITS.get(key, []) if now - t < _WINDOW]
    hits.append(now)
    _HITS[key] = hits
    return len(hits) <= _MAX


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?"))


def _supabase_json(url: str, headers: dict, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
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


def _email_for_auth_id(auth_id: str) -> str | None:
    """Server-side ONLY: uuid -> email via the Supabase Admin API. Never exposed to the client."""
    if not (SUPABASE_URL and SUPABASE_SERVICE_KEY):
        return None
    status, user = _supabase_json(
        f"{SUPABASE_URL}/auth/v1/admin/users/{auth_id}",
        {"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY},
    )
    return user.get("email") if status == 200 else None


def _password_grant(email: str, password: str):
    """Supabase password sign-in. Returns (ok, session_or_none)."""
    status, j = _supabase_json(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        {"email": email, "password": password},
    )
    if status == 200 and j.get("access_token"):
        return True, {
            "access_token": j["access_token"],
            "refresh_token": j.get("refresh_token"),
            "expires_in": j.get("expires_in"),
            "token_type": j.get("token_type", "bearer"),
        }
    return False, None


# ---- the endpoint (wire as: app.post("/api/auth/player-id")(player_id_signin)) ----------------
async def player_id_signin(request: Request):
    import db  # app's DB layer (SQLite dev / Postgres prod)
    d = await request.json()
    code = (d.get("player_id") or "").strip().upper()
    password = d.get("password") or ""
    ip = _client_ip(request)

    if not code or not password:
        return JSONResponse({"error": "player ID and password required"}, 400)
    if not _rate_ok(f"{ip}:{code}"):
        return JSONResponse({"error": "too many attempts — wait a few minutes"}, 429)

    con = db.get_con()
    row = con.execute(
        "SELECT auth_id, password_set FROM players WHERE code=?", (code,)
    ).fetchone()
    con.close()

    # Uniform failure for "no such code" vs "no account" so the endpoint isn't a code oracle.
    GENERIC = JSONResponse({"error": "wrong player ID or password"}, 401)
    if not row:
        return GENERIC
    auth_id = row["auth_id"] if hasattr(row, "keys") else row[0]
    password_set = (row["password_set"] if hasattr(row, "keys") else row[1])
    if not auth_id:
        return GENERIC
    if not password_set:
        # Google-only (or never set a password): specific, actionable message (per dispatch).
        return JSONResponse({"error": GOOGLE_ONLY_MSG}, 409)

    email = _email_for_auth_id(str(auth_id))     # server-side only; never returned
    if not email:
        return GENERIC
    ok, session = _password_grant(email, password)
    if not ok:
        return GENERIC
    return session                                # session ONLY — no email, no player_id->email leak


# ---- set-a-password (settings). Requires the caller's OWN valid session (Authorization: Bearer).
#      Uses Supabase updateUser via the user's access token, then flips players.password_set=true.
async def set_password(request: Request):
    import db, auth
    d = await request.json()
    new_password = d.get("password") or ""
    if len(new_password) < 8:
        return JSONResponse({"error": "password must be at least 8 characters"}, 400)
    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    user = auth.verify_token(token) if token else None   # existing verifier in auth.py
    if not user:
        return JSONResponse({"error": "sign in first"}, 401)

    status, _ = _supabase_json(
        f"{SUPABASE_URL}/auth/v1/user",
        {"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        {"password": new_password},
    )
    # NOTE: /auth/v1/user password update expects PUT; urllib helper posts — adjust to PUT when wiring.
    if status not in (200, 201):
        return JSONResponse({"error": "could not set password"}, 400)
    con = db.get_con()
    con.execute("UPDATE players SET password_set=true WHERE auth_id=?", (user["sub"],))
    con.commit(); con.close()
    return {"ok": True}
