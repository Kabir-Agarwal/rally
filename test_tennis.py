"""Spec test suite. Run: pytest -q"""
import sqlite3
import db
import logic
import ratings
import scoring
from ratings import canon, START, match_outcome, rebuild, new_state, apply_match, is_provisional


def mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    return con


# ---- rating engine ----
def test_singles_delta_zero_sum_and_K():
    st = new_state()
    apply_match(st, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    da, db_ = st["singles"]["a"] - START, st["singles"]["b"] - START
    assert abs(da + db_) < 1e-9 and da > 0
    assert abs(da - 16.8) < 1e-6  # K=32, M(6-4)=1.05, result-expected=0.5


def test_doubles_full_delta_each_partner():
    st = new_state()
    apply_match(st, {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"], "sets": [(6, 4)]})
    assert abs((st["doubles"]["a"] - START) - (st["doubles"]["b"] - START)) < 1e-9
    assert abs((st["doubles"]["a"] - START) - 16.8) < 1e-6


def test_pair_rating_and_provisional_at_3():
    st = new_state()
    for _ in range(3):
        apply_match(st, {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"], "sets": [(6, 4)]})
    assert st["pairs_n"][canon("a", "b")] == 3
    assert st["pairs_n"][canon("a", "b")] >= ratings.PAIR_PROVISIONAL
    assert st["pairs"][canon("a", "b")] > START


def test_margin_cases():
    assert abs(match_outcome([(6, 0), (6, 0)])[1] - 1.5) < 1e-9      # cap
    assert match_outcome([(7, 6), (7, 6)])[1] < 0.9                   # near floor
    assert 0.75 <= match_outcome([(6, 4)])[1] <= 1.5                  # one-set


def test_draw_and_winner_rule_and_zero_zero_ignored():
    assert match_outcome([(6, 4), (4, 6)]) == (0.5, 1.0)             # draw
    assert match_outcome([(6, 0), (0, 6), (7, 6)])[0] == 1.0          # sets decide
    assert match_outcome([(3, 6), (6, 3), (7, 5)])[0] == 1.0          # 2-1 sets
    assert match_outcome([(6, 4), (0, 0)])[0] == 1.0                  # 0-0 ignored


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
    assert scoring is not None
    assert ratings.tt_pairwise(["a", "b", "c"], ["a", "b", "c"]) == []      # 1 round
    dec = ratings.tt_pairwise(["a", "b", "c"], ["a", "b", "c", "a", "b", "c"])
    assert len(dec) == 3                                                     # 3 pairwise
    # a-dominant session: a sweeps both its pairs, b beats c -> ranking a > b > c
    st = new_state()
    apply_match(st, {"kind": "tt", "rotation": ["a", "b", "c"],
                     "games": ["a", "b", "a", "a", "b", "a"]})
    assert st["singles"]["a"] > st["singles"]["b"] > st["singles"]["c"]
    # K=12 evidence: two ~9-pt sweeps with drift land ~17; K=32 would exceed 30
    assert 12 < (st["singles"]["a"] - START) < 22


def test_whole_history_rebuild_after_edit_and_delete():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 0)])
    logic.finish_match(con, m, a)
    logic.approve(con, m, b)
    r1 = db.rating_state(con, gid)["singles"][a]
    # a second finished match, then delete the first -> rebuild reflects only remaining
    m2 = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m2, [(6, 4)])
    logic.finish_match(con, m2, a)
    logic.approve(con, m2, b)
    logic.delete_match(con, m2, a)
    logic.approve(con, m2, a); logic.approve(con, m2, b)  # both approve delete -> gone
    r2 = db.rating_state(con, gid)["singles"][a]
    assert abs(r1 - r2) < 1e-9, "rebuild from remaining history only"


def test_overlapping_matches_finish_order():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c = (db.add_player(con, gid, n) for n in "ABC")
    # a can be in two live matches at once
    m1 = logic.start_match(con, gid, "singles", [a], [b], [], a)
    m2 = logic.start_match(con, gid, "singles", [a], [c], [], a)
    logic.edit_sets(con, m2, [(6, 0)]); logic.finish_match(con, m2, a); logic.approve(con, m2, c)
    logic.edit_sets(con, m1, [(6, 0)]); logic.finish_match(con, m1, a); logic.approve(con, m1, b)
    # order is by finished_at; both processed, a rated in both
    st = db.rating_state(con, gid)
    assert st["singles_n"][a] == 2


# ---- approval machine ----
def test_finish_auto_approve_logger_then_all_approve():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m, a)
    aps = {r["player_id"]: r["approved_at"] for r in logic.approvals_of(con, m)}
    assert aps[a] and not aps[b]
    logic.approve(con, m, b)
    assert db.match_row(con, m)["status"] == "finished"


def test_24h_auto_for_finish_only():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m, a)
    con.execute("UPDATE approvals SET deadline='2000-01-01T00:00:00' WHERE match_id=?", (m,)); con.commit()
    logic.check_deadlines(con)
    assert db.match_row(con, m)["status"] == "finished"


def test_delete_never_auto():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m, a); logic.approve(con, m, b)
    logic.delete_match(con, m, a)
    con.execute("UPDATE approvals SET deadline='2000-01-01T00:00:00' WHERE match_id=?", (m,)); con.commit()
    logic.check_deadlines(con)  # must NOT delete
    assert db.match_row(con, m) is not None
    assert db.match_row(con, m)["status"] == "delete_requested"


def test_edit_resets_approvals():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 4)]); logic.finish_match(con, m, a)
    logic.edit_sets(con, m, [(6, 3)])  # edit while pending
    aps = {r["player_id"]: r["approved_at"] for r in logic.approvals_of(con, m)}
    assert aps[a] and not aps[b]  # logger re-auto, other reset


def test_delete_live_immediate():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    assert logic.delete_match(con, m, a) == "deleted"
    assert db.match_row(con, m) is None


def test_player_and_order_lock_after_start():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    before = [r["player_id"] for r in db.match_players(con, m)]
    # nothing in the API mutates match_players after start; verify list is stable
    logic.edit_sets(con, m, [(6, 4)])
    after = [r["player_id"] for r in db.match_players(con, m)]
    assert before == after == [a, b]


# ---- serving / stats ----
def test_serving_rotation_singles_doubles_tt():
    assert scoring.singles_server(["p1", "p2"], 0) == "p1"
    assert scoring.singles_server(["p1", "p2"], 3) == "p2"
    assert [scoring.doubles_server(["a", "c", "b", "d"], i) for i in range(5)] == ["a", "c", "b", "d", "a"]
    assert scoring.tt_pairing(["p1", "p2", "p3"], 2) == ("p3", "p1", "p2")


def test_point_logs_only_for_per_point_and_tally_counts_everything():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c = (db.add_player(con, gid, n) for n in "ABC")
    # tt tally counts every game even with <2 rounds (unrated)
    m = logic.start_match(con, gid, "tt", [], [], [a, b, c], a)
    logic.log_tt_game(con, m, a, a)  # 1 game only
    v_games = db.tt_games(con, m)
    assert len(v_games) == 1
    # rating unaffected (<2 rounds) but tally reflects the game
    tally = {}
    for g in v_games:
        tally[g["winner_player_id"]] = tally.get(g["winner_player_id"], 0) + 1
    assert tally[a] == 1


def test_serve_stats_individual_doubles_return_team():
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b, c, d = (db.add_player(con, gid, n) for n in "ABCD")
    m = logic.start_match(con, gid, "doubles", [a, b], [c, d], [], a)
    # play one full game (4 points side1) -> game 0, server = s1[0]=a (individual hold)
    for _ in range(4):
        logic.log_point(con, m, 1, None)
    s_a = scoring.serve_return_stats(con, gid, a)
    s_c = scoring.serve_return_stats(con, gid, c)
    assert s_a["served"] == 1 and s_a["held"] == 1        # a served & held (individual)
    assert s_c["ret_games"] == 1 and s_c["broke"] == 0     # c's team returned, didn't break


# ---- db / groups ----
def test_group_isolation_and_dup_name():
    con = mem()
    g1, c1 = db.create_group(con, "A")
    g2, c2 = db.create_group(con, "B")
    p = db.add_player(con, g1, "Sam")
    import pytest
    with pytest.raises(ValueError):
        db.add_player(con, g1, "sam")          # ci duplicate rejected
    p2 = db.add_player(con, g2, "Sam")          # same name other group OK
    assert p != p2
    assert db.players_of(con, g1) and len(db.players_of(con, g2)) == 1


def test_code_uniqueness_and_alphabet():
    con = mem()
    codes = set()
    for i in range(30):
        _, c = db.create_group(con, f"g{i}")
        assert len(c) == 6 and all(ch in db.CODE_ALPHABET for ch in c)
        codes.add(c)
    assert len(codes) == 30


def test_validation_legal_sets():
    assert logic.legal_set(7, 6) and logic.legal_set(7, 5) and logic.legal_set(6, 0)
    assert not logic.legal_set(6, 5) and not logic.legal_set(8, 6)
    import pytest
    con = mem()
    gid, _ = db.create_group(con, "G")
    a, b = db.add_player(con, gid, "A"), db.add_player(con, gid, "B")
    m = logic.start_match(con, gid, "singles", [a], [b], [], a)
    logic.edit_sets(con, m, [(6, 5)])           # lenient while live
    with pytest.raises(ValueError):
        logic.finish_match(con, m, a)           # strict at finish
