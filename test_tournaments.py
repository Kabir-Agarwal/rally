"""Tournament bracket engine (SPEC Y3 — ADD tournaments: 4–32 draws, BYEs, live brackets).

Proves the engine the tournaments feature-block is built on: draws are 4..32 and round up to a power
of two, BYEs pad the gap and go to the top seeds, and winners advance LIVE to a single champion.
"""
import pytest
import tournaments as T


def test_check_holds():
    assert T.check() is True                                # the real engine self-check


def test_draw_bounds_round_up_to_power_of_two():
    assert [T.bracket_size(n) for n in (4, 5, 8, 9, 16, 17, 32)] == [4, 8, 8, 16, 16, 32, 32]
    for bad in (3, 33, 0, -1):
        with pytest.raises(ValueError):
            T.bracket_size(bad)


def test_full_power_of_two_draw_has_no_byes():
    r1 = T.first_round([f"P{i}" for i in range(8)])
    assert len(r1) == 4                                      # 8 entrants -> 4 first-round matches
    assert all(m["a"] is not None and m["b"] is not None for m in r1)
    assert all(m["winner"] is None for m in r1)             # nothing decided yet


def test_byes_pad_to_power_of_two_and_go_to_top_seeds():
    ents = [f"S{i}" for i in range(1, 6)]                    # 5 entrants -> size 8 -> 3 BYEs
    r1 = T.first_round(ents)
    byes = [m for m in r1 if m["a"] is None or m["b"] is None]
    assert len(byes) == 3
    advanced = {m["winner"] for m in byes}
    assert advanced == {"S1", "S2", "S3"}                   # top three seeds get the BYEs
    assert all(m["winner"] == (m["a"] or m["b"]) for m in byes)   # BYE auto-advances the player


def test_live_advance_to_a_single_champion():
    ents = [f"S{i}" for i in range(1, 7)]                    # 6-draw, with 2 BYEs
    rank = {e: i for i, e in enumerate(ents)}
    bracket, champ = T.play(ents, lambda a, b: a if rank[a] < rank[b] else b)
    assert [len(rnd) for rnd in bracket] == [4, 2, 1]       # collapses round by round
    assert champ == "S1"                                    # top seed wins a seed-ordered draw
    assert T.champion(bracket) == "S1"


def test_top_two_seeds_can_only_meet_in_the_final():
    ents = [f"S{i}" for i in range(1, 9)]
    r1 = T.first_round(ents)
    top = {m["a"] for m in r1[: len(r1) // 2]} | {m["b"] for m in r1[: len(r1) // 2]}
    assert ("S1" in top) != ("S2" in top)                   # #1 and #2 in opposite halves


def test_cannot_advance_an_undecided_round():
    r1 = T.first_round([f"P{i}" for i in range(8)])         # full draw, nothing decided
    assert T.champion([r1]) is None
    with pytest.raises(ValueError):
        T.next_round(r1)


def test_rejects_none_and_duplicate_entrants():
    with pytest.raises(ValueError):
        T.first_round(["A", None, "B", "C"])                # None is the BYE sentinel, not an entrant
    with pytest.raises(ValueError):
        T.first_round(["A", "A", "B", "C"])                 # a player can't be in the draw twice
