"""Round-robin league engine (SPEC Y3 — ADD round-robin leagues).

Proves the engine the leagues feature-block is built on: every entrant plays every other exactly once,
odd counts carry a BYE per round, and a standings table ranks the field live by points then head-to-head.
"""
from itertools import combinations

import pytest

import leagues as L


def test_check_holds():
    assert L.check() is True                                    # the real engine self-check


def test_complete_round_robin_every_pair_once():
    ents = [f"P{i}" for i in range(6)]
    pairs = [frozenset((m["a"], m["b"])) for rnd in L.schedule(ents) for m in rnd if not L.is_bye(m)]
    assert len(pairs) == 6 * 5 // 2                             # n(n-1)/2 games
    assert set(pairs) == {frozenset(p) for p in combinations(ents, 2)}   # exactly the full set
    assert len(set(pairs)) == len(pairs)                       # no pair played twice


def test_even_league_has_no_byes_and_clean_rounds():
    sch = L.schedule([f"P{i}" for i in range(4)])
    assert len(sch) == 3 and all(len(r) == 2 for r in sch)     # 4 players -> 3 rounds x 2 games
    assert all(not L.is_bye(m) for r in sch for m in r)


def test_odd_league_gives_each_player_exactly_one_bye():
    sch = L.schedule([f"P{i}" for i in range(5)])
    assert len(sch) == 5
    rested = [(m["a"] or m["b"]) for r in sch for m in r if L.is_bye(m)]
    assert sorted(rested) == [f"P{i}" for i in range(5)]       # everyone sits out once
    for rnd in sch:                                            # nobody double-booked in a round
        seen = [x for m in rnd for x in (m["a"], m["b"]) if x is not None]
        assert len(seen) == len(set(seen))


def test_live_standings_of_a_seed_ordered_league():
    ents = [f"S{i}" for i in range(4)]
    rank = {e: i for i, e in enumerate(ents)}
    _, table = L.play(ents, lambda a, b: a if rank[a] < rank[b] else b)
    rows = {r["player"]: r for r in table}
    assert rows["S0"]["wins"] == 3 and rows["S0"]["rank"] == 1  # top seed sweeps
    assert rows["S3"]["wins"] == 0 and rows["S3"]["rank"] == 4  # bottom seed loses all
    assert all(r["played"] == 3 for r in table)                # everyone played n-1
    assert sorted(r["rank"] for r in table) == [1, 2, 3, 4]


def test_head_to_head_breaks_a_points_tie():
    ents = ["A", "B", "C", "D"]
    res = [("A", "B"), ("A", "C"), ("D", "A"), ("B", "C"), ("B", "D"), ("C", "D")]
    ms = [{"a": w, "b": l, "winner": w} for (w, l) in res]      # A,B on 2 pts; C,D on 1 pt
    ranks = {r["player"]: r["rank"] for r in L.standings(ents, ms)}
    assert ranks["A"] < ranks["B"]                             # A beat B -> A above B
    assert ranks["C"] < ranks["D"]                             # C beat D -> C above D


def test_circular_tie_shares_a_rank():
    ents = ["A", "B", "C", "D"]
    res = [("A", "B"), ("B", "C"), ("C", "A"),                 # cycle: each 1 win among themselves
           ("A", "D"), ("B", "D"), ("C", "D")]                 # all three beat D
    ms = [{"a": w, "b": l, "winner": w} for (w, l) in res]
    ranks = {r["player"]: r["rank"] for r in L.standings(ents, ms)}
    assert ranks["A"] == ranks["B"] == ranks["C"] == 1         # unbreakable tie -> shared rank
    assert ranks["D"] == 4


def test_empty_and_bogus_results():
    fresh = L.standings(["A", "B", "C"], [])                    # nothing played
    assert all(r["played"] == 0 and r["rank"] == 1 for r in fresh)
    with pytest.raises(ValueError):
        L.standings(["A", "B", "C"], [{"a": "A", "b": "B", "winner": "Z"}])   # winner didn't play
    with pytest.raises(ValueError):
        L.standings(["A", "B", "C"], [{"a": "A", "b": "X", "winner": "A"}])   # entrant not in league


def test_rejects_out_of_range_and_bad_entrants():
    for bad in ([f"P{i}" for i in range(2)], [f"P{i}" for i in range(33)],
                ["A", "A", "B"], ["A", None, "B"]):
        with pytest.raises(ValueError):
            L.schedule(bad)
