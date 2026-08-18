"""Earned-from-0 card stats contract — the player card's numbers are EARNED by playing, starting
from zero, never seeded or self-rated. Frozen so a later block can't put a number on the card that
wasn't earned on court (SPEC Y2).

Y2 KEEP: earned-from-0 card stats. Y2 also SKIPs the self-rating slider onboarding — the two are the
same rule seen from both ends: a player starts at the shared baseline with an EMPTY record and earns
every card stat by playing counted matches; nobody onboards with an assigned number. Rally is LIVE
and Y3 features land block by block (item #2); tournaments, leagues and the practice-vs-rated split
all feed the card, and Y4 adds a skill rating on it. Freeze what the card is made of before those land.

The card is app.player_payload(con, gid, pid): singles/doubles rating (ratings.START baseline until
earned), singles_n/doubles_n match counts, singles_prov/doubles_prov provisional flags (n <
ratings.MIN_MATCHES), wins/losses and the last-5 form — every field derived ONLY from status='counted'
matches. check() drives the REAL payload on an in-memory DB and fails loud if any of that regressed,
same shape as chemistry.check() / deletion.check(), wired into the same deploy.py preflight.
"""
import db
import logic
import ratings

# Frozen: a rating is provisional (unproven) until this many counted matches are EARNED. Mirrors the
# chemistry pair gate — a later block that means to move it must change it in BOTH ratings.py AND here.
RANKED_GATE = 5


def _fresh():
    con = db.connect(":memory:")
    con.executescript(db.SCHEMA)
    return con


def _mk(con, name):
    pid = db.gen_uuid()
    db.create_player(con, pid, name)
    return pid


def _counted(con, w, l):
    """Play one COUNTED singles match: w beats l 6-4, both approve (the only way a stat is earned)."""
    mid = logic.start_match(con, None, "singles", [w], [l], [], w)  # logger w auto-approves on finish
    logic.edit_sets(con, mid, [(6, 4)])
    logic.finish_match(con, mid)   # -> pending_approval (only l outstanding)
    logic.approve(con, mid, l)     # -> counted
    return mid


def check():
    """Fail loud (ValueError) if the earned-from-0 card-stats contract regressed. True when clean."""
    from app import player_payload            # the REAL card the user sees; deferred (boots app once)
    card = lambda con, pid: player_payload(con, None, pid)
    base = round(ratings.START)
    bad = []

    # 1. FROM ZERO — a brand-new player has an all-zero, un-seeded card: empty record, rating exactly
    #    at baseline, both modes provisional. This is the anti-self-rating-onboarding guarantee
    #    (Y2 SKIP self-rating slider): you don't start with a number, you start at zero and earn it.
    con = _fresh()
    c = card(con, _mk(con, "New"))
    got = (c["wins"], c["losses"], c["last5"], c["singles_n"], c["doubles_n"], c["pairs"])
    if got != (0, 0, [], 0, 0, []):
        bad.append(f"a brand-new player's card is not empty: {got} (want (0,0,[],0,0,[]))")
    if c["singles"] != base or c["doubles"] != base:
        bad.append(f"a brand-new player is seeded off baseline: singles={c['singles']} doubles={c['doubles']} "
                   f"(want {base} — card stats are earned from 0, never assigned)")
    if not (c["singles_prov"] and c["doubles_prov"]):
        bad.append("a brand-new player is not provisional (an unearned rating must not read as ranked)")
    # Y4 skill rating is a card number too: earned from 0, never seeded, provisional until ranked.
    if c["skill"] != base or not c["skill_prov"] or c["skill_n"] != 0:
        bad.append(f"a brand-new player's skill rating is seeded/ranked: skill={c['skill']} prov={c['skill_prov']} "
                   f"n={c['skill_n']} (want {base}, provisional, 0 — the FIFA-card skill is earned from 0)")
    # Y4 form count is the other card number: zero (Dormant) until activity/reputation is earned.
    if c["form"] != 0 or c["form_band"] != "Dormant":
        bad.append(f"a brand-new player's form count is non-zero: form={c['form']} band={c['form_band']!r} "
                   f"(want 0/Dormant — the form count is earned from 0)")

    # 2. EARNED — one counted singles win moves the card off zero for BOTH players: the winner earns a
    #    W and a rating above baseline, the loser an L and a rating below it.
    con = _fresh()
    w, l = _mk(con, "W"), _mk(con, "L")
    _counted(con, w, l)
    cw, cl = card(con, w), card(con, l)
    if (cw["wins"], cw["losses"], cw["last5"], cw["singles_n"]) != (1, 0, ["W"], 1):
        bad.append(f"winner card after one counted match is {(cw['wins'], cw['losses'], cw['last5'], cw['singles_n'])} "
                   f"(want (1,0,['W'],1))")
    if cw["singles"] <= base:
        bad.append(f"winner rating {cw['singles']} did not rise above baseline {base} (the win was not earned)")
    if (cl["wins"], cl["losses"], cl["last5"], cl["singles_n"]) != (0, 1, ["L"], 1):
        bad.append(f"loser card after one counted match is {(cl['wins'], cl['losses'], cl['last5'], cl['singles_n'])} "
                   f"(want (0,1,['L'],1))")
    if cl["singles"] >= base:
        bad.append(f"loser rating {cl['singles']} did not drop below baseline {base}")
    # Y4 form is earned by ACTIVITY: a just-played counted match is recent, so both players'
    # form rises off zero (win or loss — form is presence, not result, unlike skill).
    if cw["form"] <= 0 or cl["form"] <= 0:
        bad.append(f"a fresh counted match left form at zero: winner={cw['form']} loser={cl['form']} "
                   f"(recent activity must earn form)")

    # 3. EARNED ONLY FROM COUNTED PLAY — an unapproved (pending) match is not yet earned and puts
    #    NOTHING on the card. player_payload counts status='counted' only.
    con = _fresh()
    w, l = _mk(con, "W"), _mk(con, "L")
    mid = logic.start_match(con, None, "singles", [w], [l], [], w)
    logic.edit_sets(con, mid, [(6, 4)])
    logic.finish_match(con, mid)             # pending_approval — l never approves, so never counted
    if db.match_row(con, mid)["status"] == "counted":
        bad.append("setup: a singly-approved match already counts (can't exercise the pending case)")
    c = card(con, w)
    if (c["wins"], c["losses"], c["last5"], c["singles_n"]) != (0, 0, [], 0):
        bad.append(f"a pending (unapproved) match already shows on the card: "
                   f"{(c['wins'], c['losses'], c['last5'], c['singles_n'])} (an unearned match must not count)")

    # 4. FORM WINDOW — last-5 is the LAST five only. After 6 earned wins, wins climbs to 6 but the
    #    form strip stays capped at 5.
    con = _fresh()
    w, l = _mk(con, "W"), _mk(con, "L")
    for _ in range(6):
        _counted(con, w, l)
    c = card(con, w)
    if c["wins"] != 6:
        bad.append(f"6 earned wins gave wins={c['wins']} (want 6)")
    if c["last5"] != ["W"] * 5:
        bad.append(f"last5 after 6 wins is {c['last5']} (want 5x'W' — the form window is the last 5)")

    # 5. PROVISIONAL until earned — a rating stays provisional until RANKED_GATE counted matches are
    #    earned, frozen at 5. A block that lowers the bar lets a thin rating pose as ranked; one that
    #    moves ratings.MIN_MATCHES without moving this (or vice-versa) trips the frozen-constant check.
    if ratings.MIN_MATCHES != RANKED_GATE:
        bad.append(f"ratings.MIN_MATCHES is {ratings.MIN_MATCHES}; earned-from-0 froze the ranked gate at {RANKED_GATE}")
    con = _fresh()
    w, l = _mk(con, "W"), _mk(con, "L")
    for _ in range(ratings.MIN_MATCHES - 1):
        _counted(con, w, l)
    if not card(con, w)["singles_prov"]:
        bad.append(f"a rating is non-provisional at {ratings.MIN_MATCHES - 1} earned matches "
                   f"(want provisional below {ratings.MIN_MATCHES})")
    _counted(con, w, l)                      # the MIN_MATCHES-th earned match
    if card(con, w)["singles_prov"]:
        bad.append(f"a rating is still provisional at {ratings.MIN_MATCHES} earned matches "
                   f"(want ranked at {ratings.MIN_MATCHES})")
    if card(con, w)["skill_prov"]:
        bad.append(f"the skill rating is still provisional at {ratings.MIN_MATCHES} counted matches (want ranked)")

    if bad:
        raise ValueError("earned-from-0 card stats regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"cardstats OK: empty card from 0, earned per counted match, provisional under {RANKED_GATE}")
