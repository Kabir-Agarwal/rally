"""Game name + real name (new model): global self-serve via /api/me/claim + /api/me/rename.
Game names are NOT globally unique any more (per-group uniqueness is a DB co-membership trigger);
these tests assert the new global behavior."""
from conftest import bearer


def _hdr(sub):
    return {"Authorization": bearer(sub)}


def test_both_names_saved_and_returned(app_client):
    c = app_client
    me = _hdr("u1")
    c.post("/api/me/claim", json={"name": "Ace", "real_name": "Alice A"}, headers=me)
    who = c.get("/api/me", headers=me).json()
    assert who["player_name"] == "Ace" and who["player_real_name"] == "Alice A"


def test_real_name_optional_and_may_duplicate(app_client):
    c = app_client
    c.post("/api/me/claim", json={"name": "One"}, headers=_hdr("u1"))
    assert c.get("/api/me", headers=_hdr("u1")).json()["player_real_name"] is None
    c.post("/api/me/claim", json={"name": "Two", "real_name": "Sam"}, headers=_hdr("u2"))
    r3 = c.post("/api/me/claim", json={"name": "Three", "real_name": "Sam"}, headers=_hdr("u3"))
    assert r3.status_code == 200          # real name may duplicate


def test_game_name_not_globally_unique(app_client):
    # NEW: two accounts may hold the same game name globally (uniqueness is per-group, enforced by
    # the DB trigger on group membership — not at global claim).
    c = app_client
    assert c.post("/api/me/claim", json={"name": "Ace"}, headers=_hdr("u1")).status_code == 200
    assert c.post("/api/me/claim", json={"name": "ace"}, headers=_hdr("u2")).status_code == 200


def test_self_rename_repeatedly(app_client):
    c = app_client
    me = _hdr("u1")
    c.post("/api/me/claim", json={"name": "First", "real_name": "R1"}, headers=me)
    assert c.post("/api/me/rename", json={"name": "Second"}, headers=me).status_code == 200
    assert c.post("/api/me/rename", json={"name": "Third", "real_name": "R3"}, headers=me).status_code == 200
    who = c.get("/api/me", headers=me).json()
    assert who["player_name"] == "Third" and who["player_real_name"] == "R3"


def test_rename_records_name_history(app_client):
    c = app_client
    me = _hdr("u1")
    r = c.post("/api/me/claim", json={"name": "Old"}, headers=me).json()
    c.post("/api/me/rename", json={"name": "New"}, headers=me)
    # old name resolvable via name_history (checked at the db layer)
    import db
    con = c.app_mod.db.connect()
    hist = con.execute("SELECT old_name FROM name_history WHERE player_id=?", (r["player_id"],)).fetchall()
    con.close()
    assert any(h["old_name"] == "Old" for h in hist)


def test_rename_requires_a_player(app_client):
    c = app_client
    # signed in but never claimed a name -> cannot rename
    assert c.post("/api/me/rename", json={"name": "X"}, headers=_hdr("u9")).status_code == 409
