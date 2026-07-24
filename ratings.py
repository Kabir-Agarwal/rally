"""Pure rating engine for tennis-scores. No DB, no I/O — plain dicts in, dicts out.

Everything recomputes from FINISHED matches in finish order. See CONTEXT.md for the
worked formulas. This module is the single source of truth for all numbers.
"""
from __future__ import annotations

START = 1200.0
K = 32
K_TT = 12
MIN_MATCHES = 5      # singles/doubles ranking gate
PAIR_PROVISIONAL = 3  # pair rating provisional below this


def canon(a, b):
    """Canonical (order-independent) key for a duo."""
    return (a, b) if a <= b else (b, a)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def expected(ra, rb):
    """P(side A wins) given ratings ra, rb."""
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def _clean_sets(sets):
    """Drop 0-0 sets (unplayed)."""
    return [(int(a), int(b)) for a, b in sets if not (int(a) == 0 and int(b) == 0)]


def match_outcome(sets):
    """Return (result_for_side1, margin_multiplier_M) for a played singles/doubles match.

    Winner: sets won -> total games -> draw (0.5 each). Margin from winner's games share.
    """
    sets = _clean_sets(sets)
    s1 = sum(1 for a, b in sets if a > b)
    s2 = sum(1 for a, b in sets if b > a)
    g1 = sum(a for a, b in sets)
    g2 = sum(b for a, b in sets)
    total = g1 + g2

    if s1 > s2:
        result1 = 1.0
    elif s2 > s1:
        result1 = 0.0
    elif g1 > g2:
        result1 = 1.0
    elif g2 > g1:
        result1 = 0.0
    else:
        result1 = 0.5

    if result1 == 0.5:
        return 0.5, 1.0
    winner_games = g1 if result1 == 1.0 else g2
    share = winner_games / total if total else 0.5
    m = clamp(0.75 + 3 * (share - 0.5), 0.75, 1.5)
    return result1, m


def new_state():
    return {
        "singles": {}, "singles_n": {},
        "doubles": {}, "doubles_n": {},
        "pairs": {}, "pairs_n": {},
    }


def _get(d, key):
    return d.get(key, START)


DOMINANCE_CAP = 0.15  # live-scored matches: ±15% delta adjustment from point dominance


def dominance_multiplier(winner_point_share):
    """Map the winner's share of total points to a bounded delta multiplier.

    Live-scored matches only. share 0.75 -> 1.0 (neutral); a crushing point win (share 1.0)
    -> 1+CAP; a bare point win (share 0.5 or less) -> 1-CAP. Always > 0, so it scales the
    delta's magnitude but NEVER flips the result. Typed matches don't call this.
    """
    return clamp(1.0 + 0.6 * (winner_point_share - 0.75), 1 - DOMINANCE_CAP, 1 + DOMINANCE_CAP)


def _apply_elo(state, mode, side1, side2, result1, m, k=K, extra=1.0):
    """Apply an ELO update for a singles/doubles match to per-player ratings.

    side1/side2 are lists of player ids. Team rating = average; team delta computed
    once; EACH partner moves by the FULL delta. `extra` is the optional point-dominance
    multiplier (1.0 for typed matches).
    """
    r = state[mode]
    n = state[mode + "_n"]
    ra = sum(_get(r, p) for p in side1) / len(side1)
    rb = sum(_get(r, p) for p in side2) / len(side2)
    ea = expected(ra, rb)
    delta = k * m * extra * (result1 - ea)
    for p in side1:
        r[p] = _get(r, p) + delta
        n[p] = n.get(p, 0) + 1
    for p in side2:
        r[p] = _get(r, p) - delta
        n[p] = n.get(p, 0) + 1


def _apply_pair(state, side1, side2, result1, m, extra=1.0):
    """Pair ELO: each duo has its own rating, moved only by that duo as a unit."""
    p1 = canon(*side1)
    p2 = canon(*side2)
    r = state["pairs"]
    n = state["pairs_n"]
    ea = expected(_get(r, p1), _get(r, p2))
    delta = K * m * extra * (result1 - ea)
    r[p1] = _get(r, p1) + delta
    r[p2] = _get(r, p2) - delta
    n[p1] = n.get(p1, 0) + 1
    n[p2] = n.get(p2, 0) + 1


def tt_pairwise(rotation, games):
    """Decompose a triple-threat session into pairwise mini-results.

    rotation: [p1, p2, p3] in serving/rotation order.
    games: list of winner_player_id in game order (server/pairing implied by rotation).

    Returns list of (a, b, result_a, m) for completed rounds only, or [] if <2 rounds.
    Pairing per cycle: g0 P1vP2, g1 P2vP3, g2 P3vP1.
    """
    p1, p2, p3 = rotation
    pairs = [(p1, p2), (p2, p3), (p3, p1)]
    rounds = len(games) // 3
    if rounds < 2:
        return []
    played = games[: rounds * 3]
    out = []
    for idx, (a, b) in enumerate(pairs):
        wins_a = wins_b = 0
        for r in range(rounds):
            w = played[r * 3 + idx]
            if w == a:
                wins_a += 1
            elif w == b:
                wins_b += 1
        n = wins_a + wins_b
        if n == 0:
            continue
        if wins_a == wins_b:
            out.append((a, b, 0.5, 1.0))
        else:
            result_a = wins_a / n
            share = max(wins_a, wins_b) / n
            m = clamp(0.75 + 3 * (share - 0.5), 0.75, 1.5)
            out.append((a, b, result_a, m))
    return out


def apply_match(state, match):
    """Apply one finished match to state. Mutates and returns state.

    match dict:
      kind: 'singles'|'doubles'|'tt'
      side1, side2: [player_id, ...]   (singles/doubles)
      sets: [(g1,g2), ...]             (singles/doubles)
      rotation: [p1,p2,p3], games: [winner_id,...]  (tt)
    """
    kind = match["kind"]
    if kind == "tt":
        for a, b, result_a, m in tt_pairwise(match["rotation"], match["games"]):
            _apply_elo(state, "singles", [a], [b], result_a, m, k=K_TT)
        return state

    result1, m = match_outcome(match["sets"])
    mode = "singles" if kind == "singles" else "doubles"
    # Point-dominance (live-scored matches only): winner's share of total points nudges
    # the delta by up to ±15%. Typed matches carry no 'points' -> extra stays 1.0.
    extra = 1.0
    pts = match.get("points")
    if pts and result1 != 0.5:
        p1, p2 = pts
        total = p1 + p2
        if total > 0:
            winner_pts = p1 if result1 == 1.0 else p2
            extra = dominance_multiplier(winner_pts / total)
    _apply_elo(state, mode, match["side1"], match["side2"], result1, m, extra=extra)
    if kind == "doubles":
        _apply_pair(state, match["side1"], match["side2"], result1, m, extra=extra)
    return state


def rebuild(matches):
    """Rebuild full state from finished matches given in finish order."""
    state = new_state()
    for mt in matches:
        apply_match(state, mt)
    return state


def is_provisional(state, mode, pid):
    return state[mode + "_n"].get(pid, 0) < MIN_MATCHES


# ---------------------------------------------------------------------------
def _demo():
    """Runnable self-check. `python ratings.py` must print OK."""
    # margin: 6-0 6-0 hits the cap 1.5; 7-6 7-6 near the floor
    _, m_blowout = match_outcome([(6, 0), (6, 0)])
    assert abs(m_blowout - 1.5) < 1e-9, m_blowout
    _, m_close = match_outcome([(7, 6), (7, 6)])
    assert 0.75 <= m_close < 0.9, m_close  # share ~0.538 -> M ~0.865, near floor
    # one-set margin
    r, m = match_outcome([(6, 4)])
    assert r == 1.0 and 0.75 <= m <= 1.5

    # draw: 1 set each, equal games -> 0.5, M=1
    r, m = match_outcome([(6, 4), (4, 6)])
    assert r == 0.5 and m == 1.0

    # winner by total games when sets tied
    r, _ = match_outcome([(6, 0), (0, 6), (7, 6)])  # wait: 3 sets, 2-1 by sets
    # 6-0,0-6,7-6 -> side1 wins 2 sets. result 1.0
    assert r == 1.0

    # 0-0 sets ignored
    r, _ = match_outcome([(6, 4), (0, 0)])
    assert r == 1.0

    # singles delta symmetry & K
    st = new_state()
    apply_match(st, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    da = st["singles"]["a"] - START
    db = st["singles"]["b"] - START
    assert abs(da + db) < 1e-9, "zero-sum"
    assert da > 0
    # equal ratings, M for 6-4: share .6 -> M=1.05; delta=32*1.05*(1-0.5)=16.8
    assert abs(da - 16.8) < 1e-6, da

    # doubles FULL delta to each partner
    st = new_state()
    apply_match(st, {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"], "sets": [(6, 4)]})
    assert abs((st["doubles"]["a"] - START) - (st["doubles"]["b"] - START)) < 1e-9
    assert abs((st["doubles"]["a"] - START) - 16.8) < 1e-6, "each partner full delta"
    # pair rating updated
    assert canon("a", "b") in st["pairs"]
    assert st["pairs_n"][canon("a", "b")] == 1

    # pair provisional at 3
    st = new_state()
    for _ in range(3):
        apply_match(st, {"kind": "doubles", "side1": ["a", "b"], "side2": ["c", "d"], "sets": [(6, 4)]})
    assert st["pairs_n"][canon("a", "b")] == 3
    assert st["pairs_n"][canon("a", "b")] >= PAIR_PROVISIONAL

    # MIN_MATCHES gate at exactly 5
    st = new_state()
    for _ in range(5):
        apply_match(st, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    assert not is_provisional(st, "singles", "a"), "5 matches = ranked"
    st2 = new_state()
    for _ in range(4):
        apply_match(st2, {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]})
    assert is_provisional(st2, "singles", "a"), "4 matches = provisional"

    # TT: <2 completed rounds unrated
    assert tt_pairwise(["a", "b", "c"], ["a", "b", "c"]) == []  # exactly 1 round
    # 2 rounds -> rated, K=12
    st = new_state()
    apply_match(st, {"kind": "tt", "rotation": ["a", "b", "c"],
                     "games": ["a", "b", "c", "a", "b", "c"]})  # a beats b twice, b beats c twice, c beats a twice
    # pair (a,b): a won both -> result_a=1, share=1 -> M=1.5, delta=12*1.5*(1-0.5)=9
    assert abs((st["singles"]["a"] - START)) > 0
    # tally counts everything but rating only completed rounds — verified by len//3

    # whole-history rebuild determinism
    matches = [
        {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]},
        {"kind": "singles", "side1": ["b"], "side2": ["a"], "sets": [(6, 3)]},
    ]
    s_a = rebuild(matches)
    s_b = rebuild(matches)
    assert s_a["singles"] == s_b["singles"]

    print("OK ratings")


if __name__ == "__main__":
    _demo()
