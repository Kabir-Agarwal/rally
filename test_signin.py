"""Fallback sign-in: per-device unique identity, guest gated to mock, no dev codes leaked."""
from pathlib import Path
from conftest import _fresh_app


def _fresh(tmp_path):
    from fastapi.testclient import TestClient
    appmod = _fresh_app(tmp_path)
    return appmod, TestClient(appmod.app)


def test_two_devices_become_two_players(tmp_path):
    appmod, c = _fresh(tmp_path)
    ta = c.post("/api/auth/guest", json={"device_id": "phone-A"}).json()["token"]
    tb = c.post("/api/auth/guest", json={"device_id": "phone-B"}).json()["token"]
    assert ta != tb
    c.post("/api/me/claim", json={"name": "Aye"}, headers={"Authorization": "Bearer " + ta})
    c.post("/api/me/claim", json={"name": "Bee"}, headers={"Authorization": "Bearer " + tb})
    pa = c.get("/api/me", headers={"Authorization": "Bearer " + ta}).json()["player_id"]
    pb = c.get("/api/me", headers={"Authorization": "Bearer " + tb}).json()["player_id"]
    assert pa and pb and pa != pb


def test_same_device_reuses_same_account(tmp_path):
    appmod, c = _fresh(tmp_path)
    t1 = c.post("/api/auth/guest", json={"device_id": "phone-A"}).json()["token"]
    t2 = c.post("/api/auth/guest", json={"device_id": "phone-A"}).json()["token"]
    assert appmod.auth.verify_token(t1)["sub"] == appmod.auth.verify_token(t2)["sub"]


def test_guest_disabled_when_supabase_configured(tmp_path):
    appmod, c = _fresh(tmp_path)
    old = appmod.auth.AUTH_MODE
    try:
        appmod.auth.AUTH_MODE = "supabase"
        assert c.post("/api/auth/guest", json={"device_id": "x"}).status_code == 400
    finally:
        appmod.auth.AUTH_MODE = old


def test_no_dev_code_shown_in_client_or_pages(tmp_path):
    appmod, c = _fresh(tmp_path)
    js = (Path(__file__).parent / "static" / "auth.js").read_text(encoding="utf-8")
    assert "Dev mode" not in js and "dev_code" not in js


def test_email_sign_in_is_gone(tmp_path):
    """Email sign-in was removed: Supabase mails a LINK unless its templates carry {{ .Token }},
    and those need custom SMTP to edit. Old cached clients must get an honest 410, and no email
    or 6-digit-code UI may remain in the bundle."""
    appmod, c = _fresh(tmp_path)
    for path in ("/api/auth/email/start", "/api/auth/email/verify"):
        r = c.post(path, json={"email": "x@y.com", "code": "123456"})
        assert r.status_code == 410, f"{path} -> {r.status_code}"
        assert "removed" in r.json()["error"]

    js = (Path(__file__).parent / "static" / "auth.js").read_text(encoding="utf-8")
    for gone in ("auEmail", "auCode", "auOtpBox", "email/start", "email/verify", "6-digit"):
        assert gone not in js, f"email sign-in leftover in the UI bundle: {gone}"
    assert not hasattr(appmod.auth, "start_email_otp"), "server-side email OTP should be deleted"


def test_signed_out_screen_offers_exactly_google_and_player_id(tmp_path):
    appmod, c = _fresh(tmp_path)
    js = (Path(__file__).parent / "static" / "auth.js").read_text(encoding="utf-8")
    assert "Continue with Google" in js
    assert "Player ID + password" in js
    assert "New here? Continue with Google." in js
