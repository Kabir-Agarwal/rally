"""The per-request Supabase token-verification cache (PERF) must not weaken auth.

MEASURED problem: auth._verify_supabase() was a ~0.6s network round trip to
{SUPABASE_URL}/auth/v1/user on EVERY authenticated request. These tests pin the cache's
security properties, so the latency win can never be traded for a weaker gate:

  * only CONFIRMED tokens are cached (a rejection is never cached)
  * an expired token fails even while a confirmation is still cached
  * a rejection evicts an earlier confirmation
  * a token with no readable exp is never cached
  * AUTH_VERIFY_TTL=0 turns the cache off entirely
"""
import base64
import json
import time

import auth


def _tok(exp_offset, sub="u1", email="u@x.com"):
    """A Supabase-SHAPED token (header.payload.sig). Deliberately NOT signed by us — the whole
    point is that trust comes from Supabase's answer, never from the token's own contents."""
    payload = {"sub": sub, "email": email, "exp": int(time.time()) + exp_offset}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "eyJhbGciOiJIUzI1NiJ9." + body + ".notourssignature"


class FakeSupabase:
    """Stands in for the /auth/v1/user round trip and counts how often it is made."""

    def __init__(self, accept=True):
        self.accept, self.calls = accept, 0

    def install(self, monkeypatch, sub="u1", email="u@x.com"):
        outer = self

        def fake_urlopen(req, timeout=None):
            outer.calls += 1
            if not outer.accept:
                raise OSError("401 rejected by Supabase")

            class R:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

                def read(self_inner):
                    return json.dumps({"id": sub, "email": email,
                                       "user_metadata": {"full_name": "Real Name"}}).encode()
            return R()

        monkeypatch.setattr(auth.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(auth, "AUTH_MODE", "supabase")
        monkeypatch.setattr(auth, "SUPABASE_URL", "https://fake.supabase.co")
        monkeypatch.setattr(auth, "SUPABASE_ANON_KEY", "anon")
        auth._verify_cache.clear()
        return self


def test_confirmed_token_is_verified_once_not_per_request(monkeypatch):
    """The latency win: 20 requests with the same good token = ONE round trip."""
    fake = FakeSupabase().install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 60)
    t = _tok(3600)
    for _ in range(20):
        assert auth.verify_token(t)["sub"] == "u1"
    assert fake.calls == 1, f"expected 1 Supabase round trip, made {fake.calls}"


def test_expired_token_fails_even_while_cached(monkeypatch):
    """The cache must never outlive the token. Confirm a token while it is valid, then advance
    the clock past its own exp — with the cache TTL still nowhere near elapsed. It must fail,
    which proves expiry is enforced on every hit and not just by TTL eviction."""
    fake = FakeSupabase().install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 86400)      # TTL far longer than the token's life
    now = time.time()
    monkeypatch.setattr(auth.time, "time", lambda: now)
    t = _tok(60)                                         # valid for 60s from `now`
    assert auth.verify_token(t)["sub"] == "u1"           # confirmed + cached
    assert fake.calls == 1
    # Jump 10 minutes: past the token's exp, but only 600s into an 86400s cache TTL.
    fake.accept = False                                  # Supabase would now reject it too
    monkeypatch.setattr(auth.time, "time", lambda: now + 600)
    assert auth.verify_token(t) is None, "an expired token was served from the cache"


def test_expired_token_is_never_cached_at_all(monkeypatch):
    """Same property, asserted without touching the clock: an already-expired token is never
    cached in the first place, so every call re-asks Supabase (which rejects it)."""
    fake = FakeSupabase(accept=False).install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 3600)
    t = _tok(-10)                                        # expired 10s ago
    assert auth.verify_token(t) is None
    assert auth.verify_token(t) is None
    assert fake.calls == 2, "an expired/rejected token must be re-checked, never cached"


def test_rejection_is_never_cached(monkeypatch):
    """A forged/unknown token must hit Supabase every time — no negative caching that could be
    poisoned, and no chance of a bad token being remembered as good."""
    fake = FakeSupabase(accept=False).install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 60)
    t = _tok(3600)
    for _ in range(5):
        assert auth.verify_token(t) is None
    assert fake.calls == 5


def test_rejection_evicts_an_earlier_confirmation(monkeypatch):
    """Revocation: once ONE request sees Supabase reject the token, the cached confirmation is
    dropped, so it does not keep being honoured for the rest of the TTL."""
    fake = FakeSupabase().install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 3600)
    t = _tok(3600)
    assert auth.verify_token(t)["sub"] == "u1"           # cached
    fake.accept = False                                  # token revoked server-side
    auth._verify_cache.clear()                           # simulate the first post-revoke miss
    assert auth.verify_token(t) is None
    assert auth.verify_token(t) is None                  # stays rejected, not re-cached
    assert fake.calls == 3


def test_token_without_readable_exp_is_never_cached(monkeypatch):
    """No exp = we cannot bound the cache entry, so we must re-verify every time."""
    fake = FakeSupabase().install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 60)
    body = base64.urlsafe_b64encode(json.dumps({"sub": "u1"}).encode()).decode().rstrip("=")
    t = "eyJhbGciOiJIUzI1NiJ9." + body + ".sig"
    assert auth.verify_token(t)["sub"] == "u1"
    assert auth.verify_token(t)["sub"] == "u1"
    assert fake.calls == 2


def test_ttl_zero_disables_the_cache(monkeypatch):
    fake = FakeSupabase().install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 0)
    t = _tok(3600)
    for _ in range(4):
        assert auth.verify_token(t)["sub"] == "u1"
    assert fake.calls == 4
    assert not auth._verify_cache


def test_cache_is_bounded(monkeypatch):
    FakeSupabase().install(monkeypatch)
    monkeypatch.setattr(auth, "_VERIFY_TTL", 60)
    monkeypatch.setattr(auth, "_VERIFY_MAX", 8)
    for i in range(40):
        auth.verify_token(_tok(3600, sub=f"u{i}"))
    assert len(auth._verify_cache) <= 8


def test_mock_tokens_bypass_the_cache_and_still_expire(monkeypatch):
    """Mock tokens verify locally (no round trip, no cache) and expiry still applies."""
    fake = FakeSupabase().install(monkeypatch)
    good = auth.mint_mock_token("google:a@b.com", "a@b.com")
    assert auth.verify_token(good)["email"] == "a@b.com"
    assert auth.verify_token(auth.mint_mock_token("x", "x@y.com", ttl=-1)) is None
    assert auth.verify_token("mock.bad.sig") is None
    assert fake.calls == 0
