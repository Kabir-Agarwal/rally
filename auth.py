"""Auth for Rally. Supabase Auth (Google) when SUPABASE_URL +
SUPABASE_ANON_KEY are set; otherwise a self-contained LOCAL MOCK so everything is testable
without keys. Server verifies a bearer token on every write. No phone/SMS.

# ponytail: mock tokens are HMAC-signed locally (no external calls); real Supabase tokens
# are verified by calling {SUPABASE_URL}/auth/v1/user with the anon key (the JWT secret is
# not required, and is not something we hold). One code path, provider chosen by env.
"""
from __future__ import annotations
import os
import json
import time
import hmac
import base64
import hashlib
import secrets
import urllib.request

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or ""
AUTH_MODE = "supabase" if (SUPABASE_URL and SUPABASE_ANON_KEY) else "mock"
_SECRET = (os.environ.get("AUTH_SECRET") or os.environ.get("ADMIN_KEY") or "dev-auth-secret").encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --- password hashing (stdlib only; no new dependency) ----------------------------------------
# scrypt ships with hashlib and is memory-hard, so it needs no bcrypt/argon2 wheel in the Vercel
# build. Parameters are stored IN the hash string, so they can be raised later without breaking
# existing rows. Only ever a salted digest — the plaintext is never stored, returned or logged.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1        # ~16 MB per verify


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. False for any malformed/absent hash — never raises."""
    try:
        algo, n, r, p, salt_b64, dk_b64 = (stored or "").split("$")
        if algo != "scrypt":
            return False
        want = _ub64(dk_b64)
        got = hashlib.scrypt(password.encode(), salt=_ub64(salt_b64),
                             n=int(n), r=int(r), p=int(p), dklen=len(want))
        return hmac.compare_digest(got, want)
    except Exception:
        return False


# --- server-minted sessions (the player-ID + password path) -----------------------------------
# Same HMAC-SHA256 envelope as the mock token, under a distinct `rally.` prefix so a production
# session is never confused with a dev mock. verify_token() accepts it locally, with NO network
# round trip — which is why it does not need (or use) the Supabase verification cache.
#
# SECURITY PROPERTIES, stated plainly:
#   * The signing key is AUTH_SECRET (or ADMIN_KEY). Anyone holding that key can mint a session
#     for ANY player. ADMIN_KEY is already god-mode, so this grants no new authority — but it
#     does mean the key must be a real secret, set as an env var, never committed.
#   * If neither variable is set we REFUSE to mint in Supabase mode, rather than silently signing
#     with the built-in "dev-auth-secret" (which would let anyone forge any session). Fail closed.
#   * The token is a bearer credential valid until `exp`. There is NO revocation list, so a
#     stolen token works until it expires; hence the deliberately short 7-day TTL, versus the
#     30-day mock token. Changing AUTH_SECRET invalidates every issued session at once.
#   * It carries only {sub, email, exp}. `sub` is the player/auth uuid, so everything downstream
#     (require_player, admin checks, group permissions) treats it exactly like a Google session.
_SECRET_SOURCE = os.environ.get("AUTH_SECRET") or os.environ.get("ADMIN_KEY") or ""
SESSION_TTL = 86400 * 7


def can_mint_sessions() -> bool:
    """False when we would be signing with the public dev default in a real deployment."""
    return bool(_SECRET_SOURCE) or AUTH_MODE != "supabase"


def mint_session(sub: str, email: str | None = None, ttl: int = SESSION_TTL) -> str:
    if not can_mint_sessions():
        raise RuntimeError("refusing to sign a session: set AUTH_SECRET (or ADMIN_KEY)")
    payload = {"sub": sub, "email": email, "exp": int(time.time()) + ttl}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest())
    return f"rally.{body}.{sig}"


def mint_mock_token(sub: str, email: str, ttl: int = 86400 * 30) -> str:
    payload = {"sub": sub, "email": email, "exp": int(time.time()) + ttl}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest())
    return f"mock.{body}.{sig}"


def _verify_mock(token: str):
    try:
        _, body, sig = token.split(".")
        exp_sig = _b64(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, exp_sig):
            return None
        payload = json.loads(_ub64(body))
        if payload.get("exp", 0) < time.time():
            return None
        return {"sub": payload["sub"], "email": payload.get("email")}
    except Exception:
        return None


# --- verification cache (PERF) --------------------------------------------
# MEASURED: /auth/v1/user is a ~0.6s network round trip, and it ran on EVERY authenticated
# request (/api/me, /api/live, /api/leaderboard, every write). With Live polling every 3s that
# is 0.6s of pure latency per poll. Cache only CONFIRMED verifications, briefly.
#
# What this does NOT weaken:
#   * A token is only ever cached AFTER Supabase itself confirmed it. Failures are never
#     cached, so a forged/garbage/unknown token still hits Supabase every single time.
#   * Expiry is enforced independently on every cache hit, from the token's own `exp`.
#     An expired token fails the moment it expires, even mid-TTL — see _unverified_exp.
#   * The cache is per-process (a serverless instance), so it dies with the instance.
# The one real, bounded cost: a token REVOKED server-side (remote sign-out) keeps working for
# at most AUTH_VERIFY_TTL seconds after its last confirmation. 60s against Supabase's own ~1h
# access-token lifetime. Set AUTH_VERIFY_TTL=0 to disable the cache entirely.
_VERIFY_TTL = int(os.environ.get("AUTH_VERIFY_TTL") or 60)
_VERIFY_MAX = 512                      # hard cap so a long-lived instance can't grow unbounded
_verify_cache: dict[str, tuple[float, int, dict]] = {}   # key -> (confirmed_at, exp, claims)


def _cache_key(token: str) -> str:
    """Never key the cache on the raw token — hash it so tokens aren't held in a dict."""
    return hashlib.sha256(token.encode()).hexdigest()


def _unverified_exp(token: str) -> int:
    """The `exp` claim read WITHOUT signature verification.

    Safe *only* because of how it is used: it can make a cached entry expire EARLIER, never
    later, and never admits a token. A token whose signature we have not confirmed cannot
    reach the cache at all, so a forged `exp` buys an attacker nothing. 0 = no readable exp,
    which we treat as "cannot vouch for expiry" -> the entry is not reusable.
    """
    try:
        payload = json.loads(_ub64(token.split(".")[1]))
        return int(payload.get("exp") or 0)
    except Exception:
        return 0


def _cache_get(token: str):
    if _VERIFY_TTL <= 0:
        return None
    hit = _verify_cache.get(_cache_key(token))
    if not hit:
        return None
    confirmed_at, exp, claims = hit
    now = time.time()
    # Both must hold: the confirmation is still fresh AND the token has not expired.
    if now - confirmed_at < _VERIFY_TTL and exp > now:
        return claims
    _verify_cache.pop(_cache_key(token), None)
    return None


def _cache_put(token: str, claims: dict) -> None:
    if _VERIFY_TTL <= 0:
        return
    exp = _unverified_exp(token)
    if exp <= time.time():
        return                          # no usable exp -> don't cache; always re-verify
    if len(_verify_cache) >= _VERIFY_MAX:
        _verify_cache.clear()           # crude but bounded; this is a latency cache, not state
    _verify_cache[_cache_key(token)] = (time.time(), exp, claims)


def _verify_supabase(token: str):
    cached = _cache_get(token)
    if cached is not None:
        return cached
    req = urllib.request.Request(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            u = json.loads(r.read())
            meta = u.get("user_metadata") or {}
            # real name from the provider profile (Google), for pre-filling the real-name field
            name = meta.get("full_name") or meta.get("name")
            claims = {"sub": u["id"], "email": u.get("email"), "name": name}
    except Exception:
        # A rejection is NEVER cached, and it evicts any earlier confirmation for this token —
        # so a revoked token stops working as soon as one request sees the rejection.
        _verify_cache.pop(_cache_key(token), None)
        return None
    _cache_put(token, claims)
    return claims


def verify_token(token: str | None):
    """Return {sub, email} for a valid token, else None."""
    if not token:
        return None
    if token.startswith("mock.") or token.startswith("rally."):
        # Both are HMAC-signed by us and verify locally in either mode — no network, so these
        # never touch the Supabase verification cache.
        return _verify_mock(token)
    if AUTH_MODE == "supabase":
        return _verify_supabase(token)
    return None


def bearer(request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


# --- sign-in flows --------------------------------------------------------
def google_mock(email: str = "tester@gmail.com"):
    """Mock 'Continue with Google' — deterministic identity for local dev/tests."""
    email = (email or "tester@gmail.com").strip().lower()
    return {"token": mint_mock_token(f"google:{email}", email), "email": email}


def client_config():
    """Public config the browser needs. anon key is designed to be public. `guest` tells the client
    whether the guest "Continue" button is allowed — only in mock mode; the client must honour it and
    never render a guest button the server would refuse."""
    return {"mode": AUTH_MODE, "supabase_url": SUPABASE_URL, "anon_key": SUPABASE_ANON_KEY,
            "guest": AUTH_MODE == "mock"}


if __name__ == "__main__":
    # self-check
    t = mint_mock_token("google:x@y.com", "x@y.com")
    assert verify_token(t)["email"] == "x@y.com"
    assert verify_token("mock.bad.sig") is None
    assert verify_token(None) is None
    print("OK auth")
