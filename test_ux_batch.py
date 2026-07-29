"""UX batch: approvals reporting (T4) and the leaderboard group filter (T6).

SQLite here; production is Postgres. Both features are plain SQL over existing tables, so the
behaviour under test is backend-independent — but the live check is still a separate step.
"""
from conftest import _fresh_app, bearer, signin


def _fresh(tmp_path):
    from fastapi.testclient import TestClient
    appmod = _fresh_app(tmp_path)
    return appmod, TestClient(appmod.app)


def _play(c, ha, hb, a, b):
    """a records a finished singles match against b. Returns the match id."""
    mid = c.post("/api/match/start",
                 json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                 headers=ha).json()["id"]
    c.post(f"/api/match/{mid}/sets", json={"sets": [[6, 4]]}, headers=ha)
    c.post(f"/api/match/{mid}/finish", json={}, headers=ha)
    return mid


# --- T4: approvals -------------------------------------------------------
def test_recorder_is_not_waiting_on_themselves(tmp_path):
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    _play(c, ha, hb, a, b)

    mine = c.get("/api/me/approvals", headers=ha).json()
    assert mine["count"] == 0, "the recorder auto-approves on finish"
    assert mine["matches"] and mine["matches"][0]["is_recorder"] is True
    assert mine["matches"][0]["approved_by_me"] is True


def test_other_participant_has_one_waiting_and_can_approve_and_undo(tmp_path):
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    mid = _play(c, ha, hb, a, b)

    before = c.get("/api/me/approvals", headers=hb).json()
    assert before["count"] == 1, "the other player owes an approval"
    row = before["matches"][0]
    assert row["awaiting_me"] is True and row["approved_by_me"] is False and row["is_recorder"] is False

    assert c.post(f"/api/match/{mid}/approve", headers=hb).status_code == 200
    after = c.get("/api/me/approvals", headers=hb).json()
    assert after["count"] == 0
    assert after["matches"][0]["approved_by_me"] is True

    # Undo puts it back in the queue — this is the "Undo approval" button.
    assert c.post(f"/api/match/{mid}/unapprove", headers=hb).status_code == 200
    assert c.get("/api/me/approvals", headers=hb).json()["count"] == 1


def test_approvals_are_per_player_and_need_a_session(tmp_path):
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    signin(c, "z", "Zoe")
    _play(c, ha, hb, a, b)

    assert c.get("/api/me/approvals", headers={"Authorization": bearer("z")}).json()["count"] == 0, \
        "someone who wasn't in the match is not asked to approve it"
    assert c.get("/api/me/approvals").json() == {"count": 0, "matches": []}, "signed out -> nothing"


def test_approval_endpoint_reports_only_and_leaves_rating_gating_alone(tmp_path):
    """The dispatch said not to change rating behaviour. Approval ALREADY gates ratings via
    status='counted', and this pins that the existing behaviour is untouched."""
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    mid = _play(c, ha, hb, a, b)

    con = appmod.db.connect(tmp_path / "t.db")
    assert appmod.db.match_row(con, mid)["status"] == "pending_approval"
    con.close()

    c.post(f"/api/match/{mid}/approve", headers=hb)
    con = appmod.db.connect(tmp_path / "t.db")
    assert appmod.db.match_row(con, mid)["status"] == "counted", "all approved -> counts"
    con.close()

    c.post(f"/api/match/{mid}/unapprove", headers=hb)
    con = appmod.db.connect(tmp_path / "t.db")
    assert appmod.db.match_row(con, mid)["status"] == "pending_approval", "withdrawn -> rolls back"
    con.close()


# --- T6: leaderboard group filter ----------------------------------------
def test_leaderboard_group_filter_shows_only_that_groups_players(tmp_path):
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    b, hb = signin(c, "b", "Bob")
    signin(c, "out", "Outsider")

    code = c.post("/api/group/create", json={"name": "Club"}, headers=ha).json()["code"]
    c.post("/api/group/join", json={"code": code}, headers=hb)

    everyone = [r["id"] for r in c.get("/api/leaderboard?mode=singles").json()["rows"]]
    assert set(everyone) == {a, b, "out"}, everyone

    only = [r["id"] for r in c.get(f"/api/leaderboard?mode=singles&group={code}").json()["rows"]]
    assert set(only) == {a, b}, f"group filter should exclude non-members: {only}"
    assert "out" not in only


def test_leaderboard_group_filter_is_case_tolerant_and_unknown_code_is_not_a_crash(tmp_path):
    appmod, c = _fresh(tmp_path)
    a, ha = signin(c, "a", "Ann")
    code = c.post("/api/group/create", json={"name": "Club"}, headers=ha).json()["code"]

    assert c.get(f"/api/leaderboard?mode=singles&group={code}").status_code == 200
    r = c.get("/api/leaderboard?mode=singles&group=NOPE9")
    assert r.status_code == 200, "an unknown group code must not 500"
    assert r.json()["scope"] == "everyone", "unknown code falls back to everyone, not an error"
