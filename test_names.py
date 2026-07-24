"""Task 1: game name + real name — save/return, uniqueness, optional/dup, self-rename."""
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


def _hdr(appmod, sub, email="x@test"):
    return {"Authorization": "Bearer " + appmod.auth.mint_mock_token(sub, email)}


def _group(appmod, c):
    return c.post("/api/group/create", json={"name": "G"}, headers=_hdr(appmod, "owner")).json()["code"]


def test_both_names_saved_and_returned(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _group(appmod, c)
    me = _hdr(appmod, "u1", "1@t")
    c.post(f"/g/{code}/api/claim-name", json={"name": "Ace", "real_name": "Alice A"}, headers=me)
    who = c.get(f"/g/{code}/api/me", headers=me).json()
    assert who["player_name"] == "Ace" and who["player_real_name"] == "Alice A"
    p = c.get(f"/g/{code}/api/meta").json()["players"][0]
    assert p["name"] == "Ace" and p["real_name"] == "Alice A"


def test_game_name_unique_within_group(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _group(appmod, c)
    c.post(f"/g/{code}/api/claim-name", json={"name": "Ace"}, headers=_hdr(appmod, "u1", "1@t"))
    dup = c.post(f"/g/{code}/api/claim-name", json={"name": "ace"}, headers=_hdr(appmod, "u2", "2@t"))
    assert dup.status_code == 409 and "taken" in dup.json()["error"].lower()


def test_real_name_optional_and_may_duplicate(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _group(appmod, c)
    # optional: no real name
    r1 = c.post(f"/g/{code}/api/claim-name", json={"name": "One"}, headers=_hdr(appmod, "u1", "1@t"))
    assert r1.status_code == 200
    assert c.get(f"/g/{code}/api/me", headers=_hdr(appmod, "u1", "1@t")).json()["player_real_name"] is None
    # two different players may share the same real name
    c.post(f"/g/{code}/api/claim-name", json={"name": "Two", "real_name": "Sam"}, headers=_hdr(appmod, "u2", "2@t"))
    r3 = c.post(f"/g/{code}/api/claim-name", json={"name": "Three", "real_name": "Sam"}, headers=_hdr(appmod, "u3", "3@t"))
    assert r3.status_code == 200


def test_self_rename_repeatedly_updates_everywhere(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _group(appmod, c)
    me = _hdr(appmod, "u1", "1@t")
    c.post(f"/g/{code}/api/claim-name", json={"name": "First", "real_name": "R1"}, headers=me)

    def game_names():
        lb = c.get(f"/g/{code}/api/leaderboard?scope=group&mode=singles").json()
        return [r["name"] for r in lb["ranked"] + lb["provisional"]]
    assert "First" in game_names()
    # rename twice, no cooldown / no admin
    assert c.post(f"/g/{code}/api/rename-me", json={"name": "Second"}, headers=me).status_code == 200
    assert c.post(f"/g/{code}/api/rename-me", json={"name": "Third", "real_name": "R3"}, headers=me).status_code == 200
    assert "Third" in game_names() and "First" not in game_names()
    who = c.get(f"/g/{code}/api/me", headers=me).json()
    assert who["player_name"] == "Third" and who["player_real_name"] == "R3"


def test_self_rename_rejects_taken_game_name(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _group(appmod, c)
    c.post(f"/g/{code}/api/claim-name", json={"name": "Taken"}, headers=_hdr(appmod, "u1", "1@t"))
    me2 = _hdr(appmod, "u2", "2@t")
    c.post(f"/g/{code}/api/claim-name", json={"name": "Mine"}, headers=me2)
    r = c.post(f"/g/{code}/api/rename-me", json={"name": "taken"}, headers=me2)
    assert r.status_code == 409


def test_rename_me_requires_a_player(tmp_path):
    appmod, c = _fresh(tmp_path)
    code = _group(appmod, c)
    # signed in but not linked -> cannot rename
    r = c.post(f"/g/{code}/api/rename-me", json={"name": "X"}, headers=_hdr(appmod, "u9", "9@t"))
    assert r.status_code == 400
