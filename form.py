"""Activity/reputation "form count" — the FIFA card's SECOND Y4 number (SPEC Y4).

Y4 wants TWO separate card numbers. The first is the Elo-style SKILL rating
(ratings.skill, item #17) — how GOOD you are. This is the second, separate one — how
ACTIVE and well-regarded you are: a recency-weighted count of recent play plus the
reputation earned on your highlights. Skill measures results; form measures presence.
The two are deliberately independent: a decorated veteran who stopped playing goes cold
here while their skill holds, and a busy newcomer runs hot here while their skill is
still provisional.

Pure, DB-free, plain values in -> one integer out — the sibling-engine shape
(ratings.py / highlights.py). Recency lives here as day-age buckets; the CALLER reads
'now' and each counted match's finished_at and passes the ages, so this module stays
I/O-free and deterministic — ratings.py's "no now() in the number engine" rule.

Activity: recent counted matches, recency-weighted — this week counts most, this quarter
least, older is out of form. A form number DECAYS; that decay is what makes it "form"
and not a lifetime match tally (which the card already shows as wins/losses).

Reputation: laurels earned on your own highlights (highlights.laurel), gold>silver>bronze.
Highlights aren't persisted until the batched migrations (item #19, SPEC Y5), so today the
caller passes no laurels and the form count == its activity half; the reputation half is
wired and proven here, waiting only for that data to exist.

check() proves the recency buckets, the laurel weighting, the combined count and the
display band — same fail-loud shape as the sibling engines, wired into deploy.py preflight.
"""

# Activity: (max age in DAYS, points) for one counted match; nearest bucket first, older = 0.
# This week is hot, this month warm, this quarter faint, older than a quarter is out of form.
ACTIVITY_BUCKETS = ((7, 3), (30, 2), (90, 1))

# Reputation: points per laurel a player's highlights have earned (highlights.LAUREL tiers).
LAUREL_POINTS = {"gold": 12, "silver": 6, "bronze": 3}

# Display bands over the count — the FIFA "form" read (cold -> on fire). Display-only and
# tunable, like ratings.tier over the skill number; the underlying count stays raw.
# ponytail: bands are cosmetic; retune thresholds freely, they don't feed any decision.
FORM_BANDS = ((0, "Dormant"), (1, "Warming"), (10, "Active"), (25, "Hot"), (50, "On Fire"))


def activity_points(ages_days):
    """Recency-weighted points from a player's counted-match ages (whole days since played).
    Each match scores by the FIRST bucket its age falls in; older than the last bucket = 0."""
    total = 0
    for age in ages_days:
        for max_age, pts in ACTIVITY_BUCKETS:
            if age <= max_age:
                total += pts
                break
    return total


def reputation_points(laurels):
    """Points from the laurels a player's highlights have earned — an iterable of
    'gold'|'silver'|'bronze' (highlights.laurel output). 'none'/unknown score 0."""
    return sum(LAUREL_POINTS.get(l, 0) for l in laurels)


def form_count(ages_days, laurels=()):
    """The activity/reputation form count as one integer: recency-weighted recent play plus
    earned reputation. Zero when a player has neither recent matches nor laurels."""
    return activity_points(ages_days) + reputation_points(laurels)


def form_band(count):
    """Named form band over the count (Dormant -> On Fire) — the card read, like ratings.tier."""
    name = FORM_BANDS[0][1]
    for floor, label in FORM_BANDS:
        if count >= floor:
            name = label
    return name


def check():
    """Fail loud (ValueError) if the form-count engine regressed. Returns True when clean."""
    bad = []

    # 1. ACTIVITY RECENCY — each match scores by its bucket; boundaries inclusive; decays to 0.
    for ages, want in [
        ([0, 3, 7], 9),        # three within a week -> 3 each
        ([8, 30], 4),          # two in the month bucket -> 2 each
        ([31, 90], 2),         # two in the quarter bucket -> 1 each
        ([91, 365], 0),        # older than a quarter -> out of form
        ([1, 10, 40, 100], 6), # one per bucket + one stale -> 3+2+1+0
        ([], 0),               # no matches -> no form
    ]:
        got = activity_points(ages)
        if got != want:
            bad.append(f"activity_points({ages}) = {got}, want {want}")

    # 2. REPUTATION — laurels weight gold>silver>bronze; 'none'/unknown add nothing.
    for laurels, want in [
        (["gold", "silver", "bronze"], 21),
        (["gold", "gold"], 24),
        (["none", "gold", "mystery"], 12),  # only the real laurel counts
        ([], 0),
    ]:
        got = reputation_points(laurels)
        if got != want:
            bad.append(f"reputation_points({laurels}) = {got}, want {want}")

    # 3. COMBINED — activity + reputation, one number; the two halves are independent.
    if form_count([0, 0], ["gold"]) != 6 + 12:
        bad.append("form_count did not sum activity + reputation")
    if form_count([1]) != 3:
        bad.append("form_count with no laurels should be activity only")
    if form_count([], []) != 0:
        bad.append("an inactive, un-decorated player must read 0 form (earned-from-0)")

    # 4. BANDS — cold to on fire; a zero-form player is Dormant, a busy one climbs.
    for count, want in [(0, "Dormant"), (1, "Warming"), (9, "Warming"),
                        (10, "Active"), (24, "Active"), (25, "Hot"),
                        (49, "Hot"), (50, "On Fire"), (200, "On Fire")]:
        got = form_band(count)
        if got != want:
            bad.append(f"form_band({count}) = {got!r}, want {want!r}")

    if bad:
        raise ValueError("form-count engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"form OK: activity buckets {ACTIVITY_BUCKETS} (days->pts), "
          f"laurels {LAUREL_POINTS}, bands {[b[1] for b in FORM_BANDS]}")
