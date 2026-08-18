"""Practice-vs-rated split (SPEC Y3 — ADD practice-vs-rated split).

Proves the split the log-a-game flow is built on: every match is rated or practice, an un-tagged
match stays rated (so nothing already logged stops counting), and — the whole point — practice
matches are logged for the record but never move the Elo rating.
"""
import pytest

import practice as P
import ratings


def test_check_holds():
    assert P.check() is True                                    # the real engine self-check


def test_modes_normalize_and_default_to_rated():
    assert P.normalize(None) == P.RATED and P.normalize("") == P.RATED   # absent -> rated (back-compat)
    assert P.normalize(" RATED ") == P.RATED                    # case/space tolerant (it's a UI toggle)
    assert P.normalize("Practice") == P.PRACTICE
    for junk in ("ranked", "friendly", "casual", "true"):
        with pytest.raises(ValueError):
            P.normalize(junk)                                   # an unknown mode is a bug, not "rated"


def test_untagged_match_is_rated():
    legacy = {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]}   # no "mode"
    assert P.is_rated(legacy) and P.mode_of(legacy) == P.RATED  # every pre-feature match keeps counting


def test_split_partitions_and_preserves_order():
    hist = [{"id": 0, "mode": "rated"}, {"id": 1, "mode": "practice"}, {"id": 2},
            {"id": 3, "mode": "PRACTICE"}, {"id": 4, "mode": "rated"}]
    rated, prac = P.split(hist)
    assert [m["id"] for m in rated] == [0, 2, 4]               # id 2 is un-tagged -> rated
    assert [m["id"] for m in prac] == [1, 3]
    assert len(rated) + len(prac) == len(hist)                 # nothing dropped or duplicated
    assert P.for_rating(hist) == rated                        # for_rating is exactly the rated slice


def test_practice_matches_do_not_move_the_rating():
    rated_m = {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)], "mode": "rated"}
    prac_m  = {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 0)], "mode": "practice"}
    mixed = [rated_m, prac_m]
    split_only = ratings.rebuild(P.for_rating(mixed))["singles"]
    assert split_only == ratings.rebuild([rated_m])["singles"]  # same as if the practice match never happened
    assert split_only != ratings.rebuild(mixed)["singles"]      # ...and counting it WOULD have moved the number
    assert ratings.rebuild(P.for_rating([prac_m]))["singles"] == {}   # a lone practice match: nobody off baseline


def test_bad_mode_fails_loud_in_the_pipeline():
    good = {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)], "mode": "rated"}
    with pytest.raises(ValueError):
        P.for_rating([good, {"mode": "ranked"}])              # a typo can't silently slip into the rating
    with pytest.raises(ValueError):
        P.split([{"mode": "friendly"}])
