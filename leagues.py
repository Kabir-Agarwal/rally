"""Round-robin leagues — everyone plays everyone, live standings table (SPEC Y3).

Y3 ADD: round-robin leagues, the sibling of tournaments (tournaments.py). Where a tournament is a
single-elimination draw that collapses to one champion, a league is a round-robin: every entrant plays
every other entrant exactly once, and a standings TABLE ranks them as results arrive. This is the pure
ENGINE the leagues feature-block is built on. Persisting a league and the Create/Manage screens belong
to the competitions hub (item #10) and batched migrations (item #19, SPEC Y5 — no session applies
schema); this module is the dependency-free, DB-free logic they'll call, so the leagues screen lands as
dummy UI now (SPEC Y1, blocks.py) with a proven engine behind it.

Model — plain lists/dicts, no DB (the same match shape as tournaments.py so a UI can render both):
  entrant  — anything hashable (a player id / name). Input order is the tiebreak order (a stable
             seeding); ranking by rating is the caller's job, the engine treats input order AS it.
  match    — {"a": entrant, "b": entrant, "winner": entrant|None}; winner None = fixture not yet played.
             A round-robin with an ODD count carries one BYE per round: {"a": entrant, "b": None} (or a
             None in "a") — that entrant rests the round. is_bye() spots it; standings ignores it.
  round    — a list of matches played in parallel (no entrant appears twice). A schedule is a list of
             rounds, round[0] first, built by the classic circle method.
  row      — a standings line {"player", "played", "wins", "losses", "points", "rank"}.

check() builds full round-robins (a 4 and an odd 5), plays one forward to a full table, and asserts
every invariant — same fail-loud shape as the other preflight guards, wired into deploy.py.
"""

MIN_LEAGUE = 3          # a round-robin needs 3+ to be a league; 2 is just a single match
MAX_LEAGUE = 32         # mirrors the tournaments 4–32 competition ceiling
# ponytail: n entrants = n(n-1)/2 fixtures (quadratic), so a 32-league is 496 games — the caller keeps
# the size sane, exactly as tournaments treats input order as the seeding. No tighter cap invented.


def _validate_entrants(entrants):
    """Trust-boundary guard shared by schedule()/standings(): 3..32 distinct, non-None entrants."""
    n = len(entrants)
    if not (MIN_LEAGUE <= n <= MAX_LEAGUE):
        raise ValueError(f"league size {n} out of range (want {MIN_LEAGUE}..{MAX_LEAGUE})")
    if any(e is None for e in entrants):
        raise ValueError("entrant cannot be None (None is the BYE sentinel)")
    if len(set(entrants)) != n:
        raise ValueError("duplicate entrant in the league")
    return n


def is_bye(match):
    """True for a rest/BYE match — one of the two slots is None (odd round-robin), so nobody wins it."""
    return match["a"] is None or match["b"] is None


def schedule(entrants):
    """Single round-robin: every entrant plays every other exactly once, grouped into rounds by the
    circle method so no entrant plays twice in a round. Even count -> n-1 rounds of n/2 matches; odd
    count -> n rounds, one BYE each (that entrant rests). Returns a list of rounds (lists of matches)."""
    n = _validate_entrants(entrants)
    players = list(entrants)
    if n % 2:
        players.append(None)                       # odd -> a phantom whose opponent takes the BYE
    m = len(players)
    fixed, rot = players[0], players[1:]           # circle method: pin one player, rotate the rest
    rounds = []
    for _ in range(m - 1):
        row = [fixed] + rot
        rounds.append([{"a": row[i], "b": row[m - 1 - i], "winner": None} for i in range(m // 2)])
        rot = rot[-1:] + rot[:-1]                   # rotate one step for the next round
    return rounds


def round_complete(rnd):
    """True once every REAL match in the round has a winner (BYE matches never get one)."""
    return all(m["winner"] is not None for m in rnd if not is_bye(m))


def standings(entrants, matches):
    """League table for these entrants from an iterable of matches. Only decided, non-BYE matches count;
    an unplayed fixture (winner None) or a BYE is skipped. 1 point per win. Ranked by points, then
    head-to-head wins WITHIN the tied group, then input order — the standard round-robin tiebreak,
    computable from winners alone (a games/sets tiebreak needs scores, a later caller's concern).

    Raises if a match names an entrant not in the league or a winner who didn't play in it."""
    order = {e: i for i, e in enumerate(entrants)}
    if len(order) != len(entrants):
        raise ValueError("duplicate entrant in the league")
    table = {e: {"player": e, "played": 0, "wins": 0, "losses": 0, "points": 0} for e in entrants}
    h2h = {}                                        # (winner, loser) -> count, for the tiebreak
    for mt in matches:
        a, b, w = mt["a"], mt["b"], mt["winner"]
        if a is None or b is None or w is None:
            continue                                # BYE or unplayed fixture — no result to record
        if a not in table or b not in table:
            raise ValueError(f"match names an entrant not in the league: {mt!r}")
        if w != a and w != b:
            raise ValueError(f"winner {w!r} did not play in match {mt!r}")
        loser = b if w == a else a
        table[w]["wins"] += 1
        table[w]["points"] += 1                     # ponytail: 1-per-win; a weighted system is a caller concern
        table[loser]["losses"] += 1
        table[w]["played"] += 1
        table[loser]["played"] += 1
        h2h[(w, loser)] = h2h.get((w, loser), 0) + 1

    rows = list(table.values())
    # Head-to-head is only meaningful among players level on points, so compute it per points-group.
    groups = {}
    for r in rows:
        groups.setdefault(r["points"], []).append(r["player"])
    h2h_in_group = {}
    for members in groups.values():
        ids = set(members)
        for p in members:
            h2h_in_group[p] = sum(h2h.get((p, o), 0) for o in ids if o != p)

    rows.sort(key=lambda r: (-r["points"], -h2h_in_group[r["player"]], order[r["player"]]))
    # Standard competition ranking: players equal on (points, in-group head-to-head) share a rank.
    prev_key, rank = None, 0
    for i, r in enumerate(rows):
        key = (r["points"], h2h_in_group[r["player"]])
        if key != prev_key:
            rank, prev_key = i + 1, key
        r["rank"] = rank
    return rows


def play(entrants, decide):
    """Run a whole round-robin LIVE to a full table. `decide(a, b)` returns the winner of a real match
    (never a BYE). Returns (schedule, table) — the "advance the live league table" verb check()/tests
    drive end to end, the round-robin analog of tournaments.play()."""
    rounds = schedule(entrants)
    for rnd in rounds:
        for m in rnd:
            if not is_bye(m):
                m["winner"] = decide(m["a"], m["b"])
    flat = [m for rnd in rounds for m in rnd]
    return rounds, standings(entrants, flat)


def check():
    """Fail loud (ValueError) if the round-robin engine regressed. Returns True when clean."""
    from itertools import combinations
    bad = []

    # 1. SIZE BOUNDS + TRUST GUARDS — a league is 3..32 distinct, non-None entrants; anything else is
    #    refused. Valid ends of the range must schedule; each bad input must raise.
    for n in (MIN_LEAGUE, MAX_LEAGUE):
        if not schedule([f"P{i}" for i in range(n)]):
            bad.append(f"{n}-league produced no schedule")
    for bad_ents in ([f"P{i}" for i in range(2)],       # too small
                     [f"P{i}" for i in range(33)],      # too big
                     ["A", "A", "B"],                   # duplicate entrant
                     ["A", None, "B"]):                 # None is the BYE sentinel, not an entrant
        try:
            schedule(bad_ents)
            bad.append(f"schedule accepted invalid entrants: {bad_ents!r}")
        except ValueError:
            pass

    # 2. COMPLETE ROUND-ROBIN — every pair meets exactly once, no pair twice. Check an even and an odd n.
    for n in (4, 5):
        ents = [f"P{i}" for i in range(n)]
        pairs = [frozenset((m["a"], m["b"])) for rnd in schedule(ents) for m in rnd if not is_bye(m)]
        want = {frozenset(p) for p in combinations(ents, 2)}
        if len(pairs) != n * (n - 1) // 2:
            bad.append(f"{n}-league has {len(pairs)} games, want {n*(n-1)//2}")
        if set(pairs) != want:
            bad.append(f"{n}-league pairings are not the complete round-robin")
        if len(set(pairs)) != len(pairs):
            bad.append(f"{n}-league repeats a pairing")

    # 3. ROUND STRUCTURE — even n: n-1 rounds of n/2, no BYE. odd n: n rounds, one BYE each, and every
    #    player rests exactly once. In every round a player appears at most once (no double-booking).
    sch4 = schedule([f"P{i}" for i in range(4)])
    if len(sch4) != 3 or any(len(r) != 2 for r in sch4) or any(is_bye(m) for r in sch4 for m in r):
        bad.append("4-league is not 3 rounds x 2 games with no BYE")
    sch5 = schedule([f"P{i}" for i in range(5)])
    if len(sch5) != 5:
        bad.append(f"5-league has {len(sch5)} rounds, want 5")
    rested = []
    for rnd in sch5:
        if sum(1 for m in rnd if is_bye(m)) != 1:
            bad.append(f"odd-league round {rnd} does not have exactly one BYE")
        seen = [x for m in rnd for x in (m["a"], m["b"]) if x is not None]
        if len(seen) != len(set(seen)):
            bad.append(f"a player is double-booked in a round: {rnd}")
        rested += [(m["a"] or m["b"]) for m in rnd if is_bye(m)]
    if sorted(rested) != [f"P{i}" for i in range(5)]:
        bad.append(f"odd-league BYEs are not one-per-player: {sorted(rested)}")

    # 4. LIVE to a full TABLE — play a 4-league with the better seed always winning: the top seed sweeps
    #    (3-0, rank 1), the bottom loses all (0-3, last), everyone played n-1, and ranks run 1..n.
    ents = [f"S{i}" for i in range(4)]
    rank = {e: i for i, e in enumerate(ents)}
    _, table = play(ents, lambda a, b: a if rank[a] < rank[b] else b)
    by_player = {r["player"]: r for r in table}
    if by_player["S0"]["wins"] != 3 or by_player["S0"]["rank"] != 1:
        bad.append(f"top seed row wrong: {by_player['S0']}")
    if by_player["S3"]["wins"] != 0 or by_player["S3"]["rank"] != 4:
        bad.append(f"bottom seed row wrong: {by_player['S3']}")
    if any(r["played"] != 3 for r in table):
        bad.append("not every entrant played n-1 games in a full round-robin")
    if sorted(r["rank"] for r in table) != [1, 2, 3, 4]:
        bad.append(f"a seed-ordered league is not ranked 1..4: {[r['rank'] for r in table]}")

    # 5. HEAD-TO-HEAD tiebreak — two players level on points are split by who won their meeting.
    #    A,B both 2 wins but A beat B -> A above B; C,D both 1 win but C beat D -> C above D.
    ents = ["A", "B", "C", "D"]
    res = [("A", "B"), ("A", "C"), ("D", "A"), ("B", "C"), ("B", "D"), ("C", "D")]
    ms = [{"a": w, "b": l, "winner": w} for (w, l) in res]
    ranks = {r["player"]: r["rank"] for r in standings(ents, ms)}
    if not (ranks["A"] < ranks["B"] and ranks["C"] < ranks["D"]):
        bad.append(f"head-to-head tiebreak failed: {ranks}")

    # 6. TABLE GUARDS — an empty result set leaves everyone level at rank 1; a bad match is rejected.
    fresh = standings(["A", "B", "C"], [])
    if not all(r["played"] == 0 and r["rank"] == 1 for r in fresh):
        bad.append("a league with no results played is not all-tied at rank 1")
    for bogus in ([{"a": "A", "b": "B", "winner": "Z"}],          # winner didn't play
                  [{"a": "A", "b": "X", "winner": "A"}]):         # entrant not in the league
        try:
            standings(["A", "B", "C"], bogus)
            bad.append(f"standings accepted a bogus match: {bogus}")
        except ValueError:
            pass

    if bad:
        raise ValueError("round-robin league engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"leagues OK: {MIN_LEAGUE}-{MAX_LEAGUE} round-robin, BYEs on odd, live standings with H2H tiebreak")
