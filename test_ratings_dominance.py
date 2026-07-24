"""Task 7: point-dominance factor (live-scored only) + boundaries."""
import ratings
from ratings import new_state, apply_match, START, dominance_multiplier, DOMINANCE_CAP


def _delta(match):
    st = new_state()
    apply_match(st, match)
    return st["singles"].get("a", START) - START if match["kind"] == "singles" \
        else st["doubles"].get("a", START) - START


def test_dominance_multiplier_boundaries():
    assert abs(dominance_multiplier(0.75) - 1.0) < 1e-9        # neutral midpoint
    assert abs(dominance_multiplier(1.0) - (1 + DOMINANCE_CAP)) < 1e-9   # crush -> +15%
    assert abs(dominance_multiplier(0.5) - (1 - DOMINANCE_CAP)) < 1e-9   # bare -> -15%
    assert dominance_multiplier(0.2) == 1 - DOMINANCE_CAP      # clamped below
    assert dominance_multiplier(1.5) == 1 + DOMINANCE_CAP      # clamped above


def test_typed_match_has_no_dominance():
    # identical sets, no 'points' -> plain margin-multiplier delta (unchanged behaviour)
    d = _delta({"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    assert abs(d - 16.8) < 1e-6                                # 32 * 1.05 * 0.5


def test_live_scored_dominant_win_boosts_delta():
    base = _delta({"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    # same games, but a won points 60-40 (share .6) -> P<1 (0.6<0.75) -> smaller delta
    close = _delta({"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)],
                    "points": (60, 40)})
    # a won points 90-10 (share .9) -> P>1 -> bigger delta
    crush = _delta({"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)],
                    "points": (90, 10)})
    assert close < base < crush
    assert abs(crush - base * dominance_multiplier(0.9)) < 1e-6


def test_dominance_never_flips_result():
    # winner (a on sets) even lost the point count -> delta shrinks but stays POSITIVE
    d = _delta({"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(7, 6)],
                "points": (40, 60)})   # a won the set but fewer points
    assert d > 0                                             # sign preserved (no flip)
    assert d >= 0.85 * (32 * ratings.match_outcome([(7, 6)])[1] * 0.5) - 1e-6


def test_doubles_dominance_applies_to_pair_too():
    st = new_state()
    apply_match(st, {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"],
                     "sets": [(6, 4)], "points": (90, 10)})
    # both individual and pair deltas scaled by the same P>1
    from ratings import canon
    ind = st["doubles"]["a"] - START
    pair = st["pairs"][canon("a", "b")] - START
    assert ind > 16.8 and pair > 16.8                       # boosted above neutral 6-4 delta
