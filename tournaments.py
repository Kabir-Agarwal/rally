"""Single-elimination tournament brackets — 4–32 draws, BYEs, live advancement (SPEC Y3).

Y3 ADD: tournaments. This is the bracket ENGINE the tournaments feature-block is built on. It turns a
seeded list of 4–32 entrants into a single-elimination draw, pads the draw up to the next power of two
with BYEs handed to the TOP seeds, and advances winners round by round so the bracket stays LIVE as
results arrive. Persisting a tournament and the Create/Manage screens belong to the competitions hub
(item #10) and batched migrations (item #19, SPEC Y5 — no session applies schema); this module is the
pure logic they'll call, kept dependency-free and testable on its own — so the tournaments screen lands
as dummy UI now (SPEC Y1, blocks.py) with a proven engine behind it.

Model — plain lists/dicts, no DB:
  entrant  — anything hashable (a player id / name / seed). Index 0 of the input = the TOP seed;
             seeding by rating is the caller's job, the engine treats input order AS the seeding.
  match    — {"a": entrant|None, "b": entrant|None, "winner": entrant|None}; a None slot is a BYE.
  round    — a list of matches. A bracket is a list of rounds, round[0] first.

check() plays whole draws (a full 4, and a 6 with BYEs) forward to a single champion and fails loud on
any invariant regression — same shape as the other preflight guards, wired into deploy.py.
"""

MIN_DRAW = 4
MAX_DRAW = 32


def bracket_size(n):
    """Smallest power of two >= n that holds a 4–32 draw. Raises ValueError outside 4..32."""
    if not isinstance(n, int) or isinstance(n, bool) or n < MIN_DRAW or n > MAX_DRAW:
        raise ValueError(f"draw size {n!r} out of range (want {MIN_DRAW}..{MAX_DRAW})")
    size = MIN_DRAW
    while size < n:
        size *= 2
    return size


def seed_slots(size):
    """Seed numbers 1..size in single-elimination bracket order, so #1 and #2 can meet only in the
    final, #1–#4 only in the semis, and so on (the classic 'fold' seeding). size must be a power of 2."""
    if size < 1 or (size & (size - 1)) != 0:
        raise ValueError(f"bracket size {size!r} must be a power of two")
    slots = [1]
    while len(slots) < size:
        pair_sum = len(slots) * 2 + 1              # each round-1 pair of seeds sums to this
        slots = [s for x in slots for s in (x, pair_sum - x)]
    return slots


def _bye_resolved(match):
    """A match with exactly one BYE (None) auto-advances the present player. BYE-vs-BYE is impossible
    in a valid 4–32 draw (fewer than half the slots are BYEs), so it's a loud error. Mutates + returns."""
    a, b = match["a"], match["b"]
    if a is None and b is None:
        raise ValueError("a match cannot be BYE vs BYE")
    if b is None:
        match["winner"] = a
    elif a is None:
        match["winner"] = b
    return match


def first_round(entrants):
    """Round 1 of the draw for these seeded entrants (index 0 = top seed). Pads to a power-of-two
    bracket with BYEs given to the top seeds, and auto-advances every BYE. 4–32 distinct entrants."""
    n = len(entrants)
    size = bracket_size(n)                          # validates 4..32
    if any(e is None for e in entrants):
        raise ValueError("entrant cannot be None (None is the BYE sentinel)")
    if len(set(entrants)) != n:
        raise ValueError("duplicate entrant in the draw")
    seed = lambda k: entrants[k - 1] if k <= n else None   # seed number (1-based) -> entrant or BYE
    order = seed_slots(size)
    return [_bye_resolved({"a": seed(order[i]), "b": seed(order[i + 1]), "winner": None})
            for i in range(0, size, 2)]


def round_complete(rnd):
    """True once every match in the round has a winner."""
    return all(m["winner"] is not None for m in rnd)


def next_round(rnd):
    """The next round, pairing the winners of a completed round. Raises if the round isn't decided.
    Rounds past the first never contain a BYE — every first-round BYE already resolved to a player."""
    if not round_complete(rnd):
        raise ValueError("cannot advance: the round still has undecided matches")
    if len(rnd) < 2:
        raise ValueError("no next round: this round is already the single (final) match")
    w = [m["winner"] for m in rnd]
    return [{"a": w[i], "b": w[i + 1], "winner": None} for i in range(0, len(w), 2)]


def champion(bracket):
    """Winner of the final, or None while the draw is unfinished. `bracket` is a list of rounds."""
    if not bracket:
        return None
    final = bracket[-1]
    return final[0]["winner"] if len(final) == 1 else None


def play(entrants, decide):
    """Run a whole draw LIVE to its champion. `decide(a, b)` returns the winner of a real match (a and
    b are never None — BYEs resolve before decide is called). Returns (bracket, champ) where bracket is
    the list of rounds. This is the "advance the live bracket" verb check()/tests drive end to end."""
    rnd = first_round(entrants)
    bracket = [rnd]
    while True:
        for m in rnd:
            if m["winner"] is None:                 # a real match (BYEs already resolved)
                m["winner"] = decide(m["a"], m["b"])
        if len(rnd) == 1:
            break
        rnd = next_round(rnd)
        bracket.append(rnd)
    return bracket, champion(bracket)


def check():
    """Fail loud (ValueError) if the bracket engine regressed. Returns True when clean."""
    bad = []

    # 1. DRAW BOUNDS — only 4..32, each size rounded UP to the next power of two.
    for n, want in [(4, 4), (5, 8), (7, 8), (8, 8), (9, 16), (16, 16), (17, 32), (32, 32)]:
        got = bracket_size(n)
        if got != want:
            bad.append(f"bracket_size({n}) = {got}, want {want}")
    for out in (3, 33, 0, -1, True):
        try:
            bracket_size(out)
            bad.append(f"bracket_size({out!r}) did not reject an out-of-range draw")
        except ValueError:
            pass

    # 2. SEEDING — every seed appears once, and #1 / #2 land in opposite halves (can only meet in the
    #    final). If this breaks, the draw stops protecting seeds and BYE placement goes with it.
    order = seed_slots(8)
    if sorted(order) != list(range(1, 9)):
        bad.append(f"seed_slots(8) is not a permutation of 1..8: {order}")
    top = set(order[: len(order) // 2])
    if (1 in top) == (2 in top):
        bad.append(f"seeds 1 and 2 are in the same half (they must only meet in the final): {order}")

    # 3. BYES — a non-full draw pads with (size - n) BYEs, all handed to the TOP seeds, and every BYE
    #    auto-advances its player. 6 entrants -> size 8 -> 2 BYEs, to seeds 1 and 2.
    ents = [f"P{i}" for i in range(1, 7)]
    r1 = first_round(ents)
    byes = [m for m in r1 if m["a"] is None or m["b"] is None]
    if len(byes) != 2:
        bad.append(f"6-entrant draw has {len(byes)} BYEs, want 2 (size 8 - 6)")
    for m in byes:
        present = m["a"] if m["b"] is None else m["b"]
        if m["winner"] != present:
            bad.append(f"BYE match {m} did not auto-advance the present player")
        if present not in (ents[0], ents[1]):
            bad.append(f"a BYE went to {present}, not a top-2 seed (BYEs belong to the top seeds)")

    # 4. LIVE to a CHAMPION — play a full 4-draw and a 6-draw (with BYEs) forward with the better seed
    #    always winning; the top seed must take it, and each bracket must collapse round by round to one.
    for ents in ([f"S{i}" for i in range(1, 5)], [f"S{i}" for i in range(1, 7)]):
        rank = {e: i for i, e in enumerate(ents)}          # lower index = better seed
        bracket, champ = play(ents, lambda a, b: a if rank[a] < rank[b] else b)
        if champ != ents[0]:
            bad.append(f"{len(ents)}-draw champion is {champ}, want top seed {ents[0]}")
        size = bracket_size(len(ents))
        want_sizes, s = [], size // 2
        while s >= 1:
            want_sizes.append(s)
            s //= 2
        got_sizes = [len(rr) for rr in bracket]
        if got_sizes != want_sizes:
            bad.append(f"{len(ents)}-draw round sizes {got_sizes}, want {want_sizes}")

    # 5. LIVE guards — a bracket is unfinished until the final is decided, and you can't skip ahead of
    #    an undecided round (the live view relies on both).
    r1 = first_round([f"Q{i}" for i in range(1, 9)])       # full 8-draw, nothing decided yet
    if champion([r1]) is not None:
        bad.append("champion() returned a winner for an undecided opening round")
    try:
        next_round(r1)                                     # r1 not complete -> must refuse
        bad.append("next_round advanced a round that still had undecided matches")
    except ValueError:
        pass

    if bad:
        raise ValueError("tournament bracket engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"tournaments OK: {MIN_DRAW}-{MAX_DRAW} draws, BYEs to top seeds, live advance to a champion")
