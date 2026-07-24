"""Onboarding: sign-in first, self-serve names, claim existing, reuse, write-gating."""
import importlib
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


def _hdr(appmod, sub="user-a", email="a@test"):
    return {"Authorization": "Bearer " + appmod.auth.mint_mock_token(sub, email)}


def _admin(appmod):
    return {"X-Admin-Key": appmod.ADMIN_KEY}


def _make_group(appmod, c, public=False):
    code = c.post("/api/group/create", json={"name": "Secret Club"}, headers=_hdr(appmod)).json()["code"]
    if public:
        c.post(f"/g/{code}/api/public", json={"is_public": True}, headers=_hdr(appmod))
    return code


# --- Task A: sign-in first; private name never leaked in the page shell ---
def test_private_group_page_hides_name_when_signed_out(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _make_group(appmod, c, public=False)
    html = c.get(f"/g/{code}/live").text          # page GET carries no auth
    assert "Secret Club" not in html              # name not rendered for a private group
    me = c.get(f"/g/{code}/api/me").json()         # no token
    assert me["signed_in"] is False and "group_name" not in me


def test_public_group_viewable_signed_out(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _make_group(appmod, c, public=True)
    html = c.get(f"/g/{code}/live").text
    assert "Secret Club" in html                  # public group shows its name
    assert c.get(f"/g/{code}/api/live").status_code == 200   # readable with no token


def test_write_rejected_without_session(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _make_group(appmod, c)
    assert c.post(f"/g/{code}/api/claim-name", json={"name": "Sam"}).status_code == 401


# --- Task B: self-serve names ---
def test_choose_name_creates_and_links_player(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _make_group(appmod, c)
    me = _hdr(appmod, "u1", "1@test")
    r = c.post(f"/g/{code}/api/claim-name", json={"name": "Sam"}, headers=me)
    assert r.status_code == 200
    who = c.get(f"/g/{code}/api/me", headers=me).json()
    assert who["player_id"] == r.json()["player_id"] and who["player_name"] == "Sam"
    # the player now really exists in the group
    meta = c.get(f"/g/{code}/api/meta").json()
    assert "Sam" in [p["name"] for p in meta["players"]]


def test_empty_and_duplicate_names_rejected(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _make_group(appmod, c)
    c.post(f"/g/{code}/api/claim-name", json={"name": "Sam"}, headers=_hdr(appmod, "u1", "1@t"))
    # empty
    assert c.post(f"/g/{code}/api/claim-name", json={"name": "  "}, headers=_hdr(appmod, "u2", "2@t")).status_code == 400
    # duplicate (case-insensitive) by a different account
    dup = c.post(f"/g/{code}/api/claim-name", json={"name": "sam"}, headers=_hdr(appmod, "u2", "2@t"))
    assert dup.status_code == 409 and "taken" in dup.json()["error"].lower()


def test_claim_existing_player(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _make_group(appmod, c)
    # admin pre-creates a player
    pid = c.post(f"/g/{code}/api/player", json={"name": "Alex"}, headers=_admin(appmod)).json()["id"]
    me = _hdr(appmod, "u9", "9@test")
    r = c.post(f"/g/{code}/api/link", json={"player_id": pid}, headers=me)
    assert r.status_code == 200
    assert c.get(f"/g/{code}/api/me", headers=me).json()["player_name"] == "Alex"


# --- Task C-ish: reuse across sign-ins, never re-ask ---
def test_second_signin_reuses_same_player(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _make_group(appmod, c)
    me = _hdr(appmod, "u1", "1@test")             # same sub == same account/device-agnostic
    first = c.post(f"/g/{code}/api/claim-name", json={"name": "Sam"}, headers=me).json()["player_id"]
    # a later sign-in (same account) resolves to the same player and cannot re-create
    assert c.get(f"/g/{code}/api/me", headers=me).json()["player_id"] == first
    again = c.post(f"/g/{code}/api/claim-name", json={"name": "Other"}, headers=me)
    assert again.status_code == 409               # already has a name -> not asked again
