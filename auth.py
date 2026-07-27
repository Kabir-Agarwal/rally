"""Auth for Rally (Task 4). Supabase Auth (Google + email OTP) when SUPABASE_URL +
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

# in-process OTP store (mock mode, dev only — serverless containers are per-instance)
_OTP: dict[str, str] = {}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


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


def _verify_supabase(token: str):
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
            return {"sub": u["id"], "email": u.get("email"), "name": name}
    except Exception:
        return None


def verify_token(token: str | None):
    """Return {sub, email} for a valid token, else None."""
    if not token:
        return None
    if token.startswith("mock."):
        return _verify_mock(token)          # mock tokens verify locally in either mode
    if AUTH_MODE == "supabase":
        return _verify_supabase(token)
    return None


def bearer(request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


# --- sign-in flows --------------------------------------------------------
def start_email_otp(email: str):
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"error": "valid email required"}
    if AUTH_MODE == "mock":
        code = f"{secrets.randbelow(1000000):06d}"
        _OTP[email] = code
        # dev_code is returned ONLY in mock mode so the flow is testable without a mailbox.
        return {"sent": True, "dev_code": code}
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/otp",
            data=json.dumps({"email": email, "create_user": True}).encode(),
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8).read()
        return {"sent": True}
    except Exception as e:
        return {"error": f"could not send code: {e}"}


def verify_email_otp(email: str, code: str):
    email = (email or "").strip().lower()
    code = (code or "").strip()
    if AUTH_MODE == "mock":
        if _OTP.get(email) and hmac.compare_digest(_OTP[email], code):
            _OTP.pop(email, None)
            return {"token": mint_mock_token(f"email:{email}", email), "email": email}
        return {"error": "invalid code"}
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/auth/v1/verify",
            data=json.dumps({"type": "email", "email": email, "token": code}).encode(),
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        return {"token": d["access_token"], "email": email}
    except Exception:
        return {"error": "invalid code"}


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
    r = start_email_otp("a@b.com")
    assert r["sent"] and "dev_code" in r
    assert "token" in verify_email_otp("a@b.com", r["dev_code"])
    assert "error" in verify_email_otp("a@b.com", "000000")
    print("OK auth")
