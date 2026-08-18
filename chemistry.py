"""Doubles-chemistry contract — the pair-rating invariants, frozen so a later block can't silently
drop them (SPEC Y2).

Y2 KEEP: doubles chemistry. Rally is LIVE and Y3 features land block by block (item #2); several of
them — tournaments, leagues, the practice-vs-rated split — touch the rating pipeline in ratings.py.
"Doubles chemistry" is the per-duo pair rating: a pair is rated as a *unit*, distinct from the two
players' individual doubles ratings, order-independent, and provisional under PAIR_PROVISIONAL
finished pair-matches (ratings.py `_apply_pair` / `state["pairs"]`; surfaced by app.py win-prob,
/api/meta and the player card's chemistry rows).

check() exercises the real ratings engine and fails loud if any of that contract regressed — same
shape as blocks.validate() / theme.check(), wired into the same deploy.py preflight, so "keep
doubles chemistry" is enforced, not hoped for. The engine is the single source of truth for the
numbers; the /api/meta keys that carry them to the UI are guarded by test_ui_support.py.
"""
import ratings
from ratings import new_state, apply_match, canon, START

# Frozen: below this many finished pair-matches a duo's chemistry is provisional. app.py reads
# ratings.PAIR_PROVISIONAL at the win-prob gate and on the player-card chemistry rows. A later block
# that means to move it must change it in BOTH ratings.py AND here — the double edit is the point.
PROVISIONAL = 3

_DBL = {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"], "sets": [(6, 4)]}
WIN, LOSE = canon("a", "b"), canon("c", "d")


def check():
    """Fail loud (ValueError) if the doubles-chemistry contract regressed. Returns True when clean."""
    bad = []

    # 1. State carries the pair slots at all — drop these and chemistry is gone.
    st = new_state()
    if "pairs" not in st or "pairs_n" not in st:
        bad.append("new_state() dropped the pair rating slots (pairs / pairs_n)")

    # 2. A finished doubles match rates the duo as a unit: a pair slot appears, counted once,
    #    winner-duo up / loser-duo down, zero-sum between the two duos.
    st = new_state()
    apply_match(st, _DBL)
    if WIN not in st["pairs"] or LOSE not in st["pairs"]:
        bad.append("a doubles match did not create a pair rating (chemistry not applied)")
    elif not (st["pairs"][WIN] > START > st["pairs"][LOSE]):
        bad.append("pair rating did not move winner-duo up / loser-duo down")
    elif abs((st["pairs"][WIN] - START) + (st["pairs"][LOSE] - START)) > 1e-9:
        bad.append("pair rating is not zero-sum between the two duos")
    if st["pairs_n"].get(WIN) != 1:
        bad.append("pair match count did not increment to 1 on one doubles match")

    # 3. Order-independent: the duo is keyed the same however the two sides are listed.
    if canon("a", "b") != canon("b", "a"):
        bad.append("canon() is no longer order-independent")
    st = new_state()
    apply_match(st, {"kind": "doubles", "side1": ["b", "a"], "side2": ["d", "c"], "sets": [(6, 4)]})
    if set(st["pairs"]) != {WIN, LOSE}:
        bad.append(f"a reversed line-up made new pair slots {sorted(st['pairs'])} "
                   f"(want {sorted([WIN, LOSE])})")

    # 4. Provisional gate frozen at PROVISIONAL, and counted one per finished pair-match.
    if ratings.PAIR_PROVISIONAL != PROVISIONAL:
        bad.append(f"PAIR_PROVISIONAL is {ratings.PAIR_PROVISIONAL}, chemistry froze it at {PROVISIONAL}")
    st = new_state()
    for _ in range(PROVISIONAL):
        apply_match(st, _DBL)
    if st["pairs_n"].get(WIN) != PROVISIONAL:   # .get: stay a clean ValueError even if pairs vanished
        bad.append(f"pair count is {st['pairs_n'].get(WIN)} after {PROVISIONAL} doubles matches "
                   f"(want {PROVISIONAL})")

    # 5. Chemistry is doubles-only — a singles match must never leak a pair rating.
    st = new_state()
    apply_match(st, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    if st["pairs"]:
        bad.append("a singles match leaked a pair rating (chemistry must be doubles-only)")

    if bad:
        raise ValueError("doubles chemistry regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"chemistry OK: per-duo pair rating, order-independent, provisional under {PROVISIONAL}")
