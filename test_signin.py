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
    tok = c.post("/api/auth/guest", json={"device_id": "d"}).json()["token"]
    c.post("/api/me/claim", json={"name": "Zed"}, headers={"Authorization": "Bearer " + tok})
    dev = c.post("/api/auth/email/start", json={"email": "x@y.com"}).json().get("dev_code", "ZZZ")
    for path in ["/", "/live", "/groups"]:
        assert dev not in c.get(path).text
