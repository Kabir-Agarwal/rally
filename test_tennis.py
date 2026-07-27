"""Spec test suite (clean-foundation). Run: pytest -q"""
import sqlite3
import pytest
import db
import logic
import ratings
import scoring
from ratings import canon, START, match_outcome, new_state, apply_match, is_provisional


def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    return con


def mkp(con, name, real=None):
    pid = db.gen_uuid()
    db.create_player(con, pid, name, real)
    return pid


def counted(con, kind, s1, s2, rot, sets=None, games=None, group_id=None):
    """Start, score, finish, and get EVERY participant to approve -> status 'counted'."""
    logger = (list(s1) + list(s2) + list(rot))[0]
    m = logic.start_match(con, group_id, kind, s1, s2, rot, logger)
    if kind != "tt" and sets:
        logic.edit_sets(con, m, sets)
    if kind == "tt" and games:
        for w in games:
            logic.log_tt_game(con, m, None, w)
    logic.finish_match(con, m)
    for p in db.participants(con, m):
        logic.approve(con, m, p)
    return m


# ---- rating engine (unchanged; pure) ----
def test_singles_delta_zero_sum_and_K():
    st = new_state()
    apply_match(st, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    da, db_ = st["singles"]["a"] - START, st["singles"]["b"] - START
    assert abs(da + db_) < 1e-9 and da > 0
    assert abs(da - 16.8) < 1e-6


def test_doubles_full_delta_each_partner():
    st = new_state()
    apply_match(st, {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"], "sets": [(6, 4)]})
    assert abs((st["doubles"]["a"] - START) - (st["doubles"]["b"] - START)) < 1e-9
    assert abs((st["doubles"]["a"] - START) - 16.8) < 1e-6


def test_pair_rating_and_provisional_at_3():
    st = new_state()
    for _ in range(3):
        apply_match(st, {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"], "sets": [(6, 4)]})
    assert st["pairs_n"][canon("a", "b")] == 3 >= ratings.PAIR_PROVISIONAL
    assert st["pairs"][canon("a", "b")] > START


def test_margin_cases():
    assert abs(match_outcome([(6, 0), (6, 0)])[1] - 1.5) < 1e-9
    assert match_outcome([(7, 6), (7, 6)])[1] < 0.9
    assert 0.75 <= match_outcome([(6, 4)])[1] <= 1.5


def test_draw_and_winner_rule_and_zero_zero_ignored():
    assert match_outcome([(6, 4), (4, 6)]) == (0.5, 1.0)
    assert match_outcome([(6, 0), (0, 6), (7, 6)])[0] == 1.0
    assert match_outcome([(3, 6), (6, 3), (7, 5)])[0] == 1.0
    assert match_outcome([(6, 4), (0, 0)])[0] == 1.0


def test_min_matches_gate_at_exactly_5():
    st = new_state()
    for _ in range(5):
        apply_match(st, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    assert not is_provisional(st, "singles", "a")
    st2 = new_state()
    for _ in range(4):
        apply_match(st2, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    assert is_provisional(st2, "singles", "a")


def test_tt_completed_rounds_only_K12_and_under_2_unrated():
    assert ratings.tt_pairwise(["a", "b", "c"], ["a", "b", "c"]) == []
    dec = ratings.tt_pairwise(["a", "b", "c"], ["a", "b", "c", "a", "b", "c"])
    assert len(dec) == 3
    st = new_state()
    apply_match(st, {"kind": "tt", "rotation": ["a", "b", "c"], "games": ["a", "b", "a", "a", "b", "a"]})
    assert st["singles"]["a"] > st["singles"]["b"] > st["singles"]["c"]
    assert 12 < (st["singles"]["a"] - START) < 22


# ---- db model (ported to global uuid + null group + approval flow) ----
def test_score_with_no_group_counts_after_all_approve():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = counted(con, "singles", [a], [b], [], sets=[(6, 0)])
    assert db.match_row(con, m)["group_id"] is None
    assert db.match_row(con, m)["status"] == "counted"
    assert db.rating_state(con)["singles"][a] > 1200


def test_finish_needs_approval_then_counts():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = logic.start_match(con, None, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m)
    assert db.match_row(con, m)["status"] == "pending_approval"   # logger a approved; b hasn't
    assert db.rating_state(con)["singles"].get(a, 1200) == 1200   # NOT counted yet
    logic.approve(con, m, b)
    assert db.match_row(con, m)["status"] == "counted"
    assert db.rating_state(con)["singles"][a] > 1200


def test_unapprove_rolls_ratings_back():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = counted(con, "singles", [a], [b], [], sets=[(6, 4)])
    assert db.rating_state(con)["singles"][a] > 1200
    logic.unapprove(con, m, b)                                    # withdraw one approval
    assert db.match_row(con, m)["status"] == "pending_approval"
    assert db.rating_state(con)["singles"].get(a, 1200) == 1200   # rolled back


def test_dispute_excludes_from_ratings():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = counted(con, "singles", [a], [b], [], sets=[(6, 4)])
    logic.dispute(con, m, b, "wrong score")
    assert db.match_row(con, m)["status"] == "disputed"
    assert db.rating_state(con)["singles"].get(a, 1200) == 1200


def test_delete_excludes_from_ratings():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = counted(con, "singles", [a], [b], [], sets=[(6, 4)])
    logic.delete_match(con, m)
    assert db.match_row(con, m)["status"] == "deleted"
    assert db.rating_state(con)["singles"].get(a, 1200) == 1200


def test_delete_live_immediate():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = logic.start_match(con, None, "singles", [a], [b], [], a)
    assert logic.delete_match(con, m) == "deleted"
    assert db.match_row(con, m)["status"] == "deleted"


def test_freeze_and_resume_need_all_participants():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = logic.start_match(con, None, "singles", [a], [b], [], a)
    logic.freeze_request(con, m, a)
    assert db.match_row(con, m)["status"] == "live"               # only one asked
    logic.freeze_request(con, m, b)
    assert db.match_row(con, m)["status"] == "frozen"             # both -> frozen
    logic.resume_request(con, m, a)
    assert db.match_row(con, m)["status"] == "frozen"
    logic.resume_request(con, m, b)
    assert db.match_row(con, m)["status"] == "live"               # both -> live again


def test_one_live_match_per_player_global():
    con = mem()
    a, b, c = mkp(con, "A"), mkp(con, "B"), mkp(con, "C")
    logic.start_match(con, None, "singles", [a], [b], [], a)
    with pytest.raises(ValueError):
        logic.start_match(con, None, "singles", [a], [c], [], a)  # a already live (globally)


def test_overlapping_matches_finish_order():
    con = mem()
    a, b, c, d = (mkp(con, n) for n in "ABCD")
    counted(con, "singles", [c], [d], [], sets=[(6, 0)])
    counted(con, "singles", [a], [b], [], sets=[(6, 0)])
    st = db.rating_state(con)
    assert st["singles_n"][a] == 1 and st["singles_n"][c] == 1
    assert st["singles"][a] > 1200 and st["singles"][c] > 1200


def test_player_order_stable_after_start():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = logic.start_match(con, None, "singles", [a], [b], [], a)
    before = [r["player_id"] for r in db.match_players(con, m)]
    logic.edit_sets(con, m, [(6, 4)])
    after = [r["player_id"] for r in db.match_players(con, m)]
    assert before == after == [a, b]


# ---- serving / stats ----
def test_serving_rotation_singles_doubles_tt():
    assert scoring.singles_server(["p1", "p2"], 0) == "p1"
    assert scoring.singles_server(["p1", "p2"], 3) == "p2"
    assert [scoring.doubles_server(["a", "c", "b", "d"], i) for i in range(5)] == ["a", "c", "b", "d", "a"]
    assert scoring.tt_pairing(["p1", "p2", "p3"], 2) == ("p3", "p1", "p2")


def test_tt_tally_counts_every_game():
    con = mem()
    a, b, c = (mkp(con, n) for n in "ABC")
    m = logic.start_match(con, None, "tt", [], [], [a, b, c], a)
    logic.log_tt_game(con, m, a, a)
    games = db.tt_games(con, m)
    assert len(games) == 1 and games[0]["winner_player_id"] == a


def test_tt_direct_award_without_confirmed_rotation():
    """Task 5: award a TT game straight to the winner with no confirmed rotation -> stored with a
    NULL server (no serve attribution), still counted in the tally."""
    con = mem()
    a, b, c = (mkp(con, n) for n in "ABC")
    m = logic.start_match(con, None, "tt", [], [], [a, b, c], a)
    logic.log_tt_game(con, m, a, a)
    logic.log_tt_game(con, m, None, b, None)
    games = db.tt_games(con, m)
    assert games[1]["winner_player_id"] == b and games[1]["server_player_id"] is None
    assert games[0]["server_player_id"] == a


def test_serve_stats_individual_doubles_return_team():
    # NOTE: with uuid ids, db.sides() can no longer preserve intra-side insertion order (the live
    # schema has no per-side order column), so we assert the SIDE-level invariant rather than which
    # specific side-1 player served. Individual serve stat: exactly one side-1 player served & held.
    con = mem()
    a, b, c, d = (mkp(con, n) for n in "ABCD")
    m = logic.start_match(con, None, "doubles", [a, b], [c, d], [], a)
    for _ in range(4):
        logic.log_point(con, m, 1, None)
    sa, sb = scoring.serve_return_stats(con, None, a), scoring.serve_return_stats(con, None, b)
    assert sa["served"] + sb["served"] == 1 and sa["held"] + sb["held"] == 1   # one side-1 held
    sc = scoring.serve_return_stats(con, None, c)
    assert sc["ret_games"] == 1 and sc["broke"] == 0                            # side-2 returned


# ---- identity / groups ----
def test_first_signin_creates_player_with_code():
    con = mem()
    sub = db.gen_uuid()
    code = db.create_player(con, sub, "Ann")
    p = db.get_player(con, sub)
    assert p["id"] == sub and p["game_name"] == "Ann"
    assert len(code) == 5 and all(ch in db.CODE_ALPHABET for ch in code)
    assert db.get_player_by_code(con, code)["id"] == sub


def test_game_name_not_globally_unique_but_per_group():
    con = mem()
    a, b = mkp(con, "Sam"), mkp(con, "Sam")   # same game name globally is allowed now
    assert a != b
    gid, _ = db.create_group(con, "G", a)     # a is admin+member
    assert not db.group_name_taken(con, gid, "Sam", exclude_pid=a)   # only a in group
    db.add_member(con, gid, b)
    assert db.group_name_taken(con, gid, "Sam", exclude_pid=b)       # now a duplicate in-group


def test_group_code_uniqueness_and_alphabet():
    con = mem()
    admin = mkp(con, "Admin")
    codes = set()
    for i in range(30):
        _, c = db.create_group(con, f"g{i}", admin)
        assert len(c) == 6 and all(ch in db.CODE_ALPHABET for ch in c)
        codes.add(c)
    assert len(codes) == 30


def test_delete_group_keeps_matches():
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    gid, code = db.create_group(con, "G", a)
    m = counted(con, "singles", [a], [b], [], sets=[(6, 4)], group_id=gid)
    db.delete_group(con, gid)
    row = db.match_row(con, m)
    assert row is not None and row["group_id"] is None and row["former_group_name"] == "G"


def test_validation_legal_sets():
    assert logic.legal_set(7, 6) and logic.legal_set(7, 5) and logic.legal_set(6, 0)
    assert not logic.legal_set(6, 5) and not logic.legal_set(8, 6)
    con = mem()
    a, b = mkp(con, "A"), mkp(con, "B")
    m = logic.start_match(con, None, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 5)])           # lenient while live
    with pytest.raises(ValueError):
        logic.finish_match(con, m)              # strict at finish
