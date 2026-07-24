"""Task 2: fallback sign-in — per-device unique identity, guest gated to mock, no dev codes."""
import importlib
from pathlib import Path
import db as dbmod


def _fresh(tmp_path):
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    from fastapi.testclient import TestClient
    return appmod, TestClient(appmod.app)


def test_two_devices_become_two_players(tmp_path):
    appmod, c = _fresh(tmp_path)
    # two different device ids -> two different tokens/accounts
    ta = c.post("/api/auth/guest", json={"device_id": "phone-A"}).json()["token"]
    tb = c.post("/api/auth/guest", json={"device_id": "phone-B"}).json()["token"]
    assert ta != tb
    code = c.post("/api/group/create", json={"name": "G"},
                  headers={"Authorization": "Bearer " + ta}).json()["code"]
    # each device names itself -> two distinct players in the group
    c.post(f"/g/{code}/api/claim-name", json={"name": "Aye"}, headers={"Authorization": "Bearer " + ta})
    c.post(f"/g/{code}/api/claim-name", json={"name": "Bee"}, headers={"Authorization": "Bearer " + tb})
    pa = c.get(f"/g/{code}/api/me", headers={"Authorization": "Bearer " + ta}).json()["player_id"]
    pb = c.get(f"/g/{code}/api/me", headers={"Authorization": "Bearer " + tb}).json()["player_id"]
    assert pa and pb and pa != pb


def test_same_device_reuses_same_account(tmp_path):
    appmod, c = _fresh(tmp_path)
    t1 = c.post("/api/auth/guest", json={"device_id": "phone-A"}).json()["token"]
    t2 = c.post("/api/auth/guest", json={"device_id": "phone-A"}).json()["token"]   # same device again
    # both tokens resolve to the same identity (sub)
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
    # the client script must never display a dev code / "Dev mode" text
    js = (Path(__file__).parent / "static" / "auth.js").read_text(encoding="utf-8")
    assert "Dev mode" not in js and "dev_code" not in js
    # a dev code returned by the OTP endpoint must not appear on any rendered page
    code = c.post("/api/auth/guest", json={"device_id": "d"}).json()["token"]
    grp = c.post("/api/group/create", json={"name": "G"}, headers={"Authorization": "Bearer " + code}).json()["code"]
    dev = c.post("/api/auth/email/start", json={"email": "x@y.com"}).json().get("dev_code", "ZZZ")
    for path in ["/", f"/g/{grp}/live", f"/g/{grp}/groups"]:
        assert dev not in c.get(path).text
