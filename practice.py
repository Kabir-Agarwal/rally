"""Practice-vs-rated split — every logged match is either RATED or PRACTICE (SPEC Y3).

Y3 ADD: the practice-vs-rated split. A logged match now carries a MODE:
  rated    — a competitive match: it feeds the Elo rating, the rankings and the ranked card
             numbers, exactly the way every match does today.
  practice — a casual/friendly hit: still logged and kept for the record, but it does NOT touch
             your rating. Practising can't cost you (or win you) rating points.

This is the pure ENGINE the split is built on — the mode classification plus the one filter the
rating rebuild runs its matches through. It is deliberately DB-free and dependency-free (the same
shape as tournaments.py / leagues.py): the `mode` column on `matches` lands with the batched
migrations (item #19, SPEC Y5 — no session applies schema), and the log-a-game toggle + the card
wiring land with the competitions hub (item #10). Until then the engine is proven and preflight-
gated, and — the prod-never-breaks invariant — an ABSENT mode reads as `rated`, so every existing
counted match keeps feeding the rating byte-for-byte as before. The split is purely additive.

Model — a match is any dict that MAY carry a "mode" key (the same optional-key shape ratings.py
already uses for "points"); everything else about the match stays the rating engine's concern:
  match["mode"] -> "rated" | "practice" | absent/None      (absent/None == rated)

check() proves the normalization, the back-compat default, the partition, and — the whole point —
that feeding a mixed history through for_rating() yields the SAME ratings as the rated matches
alone (practice contributes exactly zero). Fail-loud, wired into deploy.py preflight beside the
tournaments/leagues engines and the Y2 guards.
"""

RATED = "rated"
PRACTICE = "practice"
MODES = (RATED, PRACTICE)
DEFAULT_MODE = RATED     # absent/None mode == rated: legacy matches keep counting (prod never breaks)


def normalize(mode):
    """Trust-boundary guard: coerce a match's mode to a canonical value.

    None / "" / absent -> rated (back-compat). "RATED" / "Rated" / " rated " -> rated (the value
    comes from a UI toggle, so tolerate case and stray space). Anything else raises ValueError — an
    unknown mode is a bug to surface, never a match silently treated as rated."""
    if mode is None or mode == "":
        return DEFAULT_MODE
    m = str(mode).strip().lower()
    if m not in MODES:
        raise ValueError(f"unknown match mode {mode!r} (want one of {MODES}, or absent for {DEFAULT_MODE})")
    return m


def mode_of(match):
    """Canonical mode of a match dict — its "mode" key normalized (absent -> rated)."""
    return normalize(match.get("mode"))


def is_rated(match):
    """True if this match feeds the rating/rankings — a competitive match, or a legacy un-tagged one."""
    return mode_of(match) == RATED


def split(matches):
    """Partition matches into (rated, practice), each preserving input order. rated + practice == all.
    Validates every match's mode, so a bad mode fails loud here rather than being silently mis-filed."""
    rated, practice = [], []
    for m in matches:
        (rated if is_rated(m) else practice).append(m)
    return rated, practice


def for_rating(matches):
    """The ONLY matches the rating engine may see: the rated ones, in order. This is the filter a
    caller runs immediately before ratings.rebuild(...) — practice matches are dropped so they never
    move a number. The whole split is this one line at the join point; everything else is naming."""
    return [m for m in matches if is_rated(m)]


def check():
    """Fail loud (ValueError) if the practice-vs-rated split regressed. Returns True when clean."""
    import ratings                                     # pure/DB-free; imported here to keep this module dependency-free
    bad = []

    # 1. NORMALIZE + TRUST GUARD — the canonical modes, case/space tolerance (it's a UI toggle), the
    #    back-compat default, and a hard refusal of anything else (an unknown mode is a bug, not "rated").
    for good, want in [("rated", RATED), ("RATED", RATED), (" Rated ", RATED),
                       ("practice", PRACTICE), ("PRACTICE", PRACTICE),
                       (None, DEFAULT_MODE), ("", DEFAULT_MODE)]:
        if normalize(good) != want:
            bad.append(f"normalize({good!r}) = {normalize(good)!r}, want {want!r}")
    for junk in ("ranked", "friendly", "casual", "rate", "prac", "0", "true"):
        try:
            normalize(junk)
            bad.append(f"normalize accepted an unknown mode: {junk!r}")
        except ValueError:
            pass

    # 2. BACK-COMPAT DEFAULT — the prod-never-breaks invariant. A match with NO "mode" key (every
    #    match logged before this feature) is rated, so it keeps feeding the rating as it always did.
    legacy = {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)]}   # no "mode"
    if not is_rated(legacy) or mode_of(legacy) != RATED:
        bad.append("a match with no mode is not rated — legacy matches would stop counting")

    # 3. PARTITION — split preserves order and covers everything (rated + practice == all), and
    #    for_rating is exactly the rated slice.
    hist = [{"id": 0, "mode": "rated"}, {"id": 1, "mode": "practice"}, {"id": 2},
            {"id": 3, "mode": "PRACTICE"}, {"id": 4, "mode": "rated"}]
    rated, practice = split(hist)
    if [m["id"] for m in rated] != [0, 2, 4]:          # id 2 has no mode -> rated
        bad.append(f"rated slice wrong: {[m['id'] for m in rated]} (want [0, 2, 4])")
    if [m["id"] for m in practice] != [1, 3]:
        bad.append(f"practice slice wrong: {[m['id'] for m in practice]} (want [1, 3])")
    if len(rated) + len(practice) != len(hist):
        bad.append("split dropped or duplicated matches (rated + practice != all)")
    if for_rating(hist) != rated:
        bad.append("for_rating is not the rated slice")

    # 4. THE POINT — practice matches move NO rating. Feed a mixed history (a rated win and a practice
    #    win between the same two players) through for_rating and rebuild: the ratings must equal the
    #    rated-match-alone rebuild, and must DIFFER from rebuilding both (proving the filter isn't a
    #    no-op). A lone practice match leaves the whole table untouched at baseline.
    rated_m = {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 4)], "mode": "rated"}
    prac_m  = {"kind": "singles", "side1": ["a"], "side2": ["b"], "sets": [(6, 0)], "mode": "practice"}
    mixed = [rated_m, prac_m]
    split_only = ratings.rebuild(for_rating(mixed))["singles"]
    rated_only = ratings.rebuild([rated_m])["singles"]
    both       = ratings.rebuild([rated_m, prac_m])["singles"]
    if split_only != rated_only:
        bad.append(f"split rating {split_only} != rated-only rating {rated_only} (practice leaked in)")
    if split_only == both:
        bad.append("counting the practice match changed nothing — the filter test is vacuous")
    lone = ratings.rebuild(for_rating([prac_m]))
    if lone["singles"] != {}:
        bad.append(f"a lone practice match moved a rating: {lone['singles']} (want nobody off baseline)")

    # 5. FAIL LOUD IN THE PIPELINE — a bad mode anywhere in a history raises at the filter, so a typo
    #    can never sneak a match into (or out of) the rating as the wrong mode.
    for op in (lambda: for_rating([rated_m, {"mode": "ranked"}]),
               lambda: split([{"mode": "friendly"}])):
        try:
            op()
            bad.append("a bad mode passed through the split silently")
        except ValueError:
            pass

    if bad:
        raise ValueError("practice-vs-rated split regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"practice OK: modes {MODES}, absent=={DEFAULT_MODE}, practice feeds the record but not the rating")
