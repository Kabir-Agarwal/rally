"""Earned-from-0 card stats contract check (SPEC Y2 — KEEP earned-from-0 card stats).

Proves the player card's numbers stay EARNED from zero as Y3 features land on the match/rating
pipeline and Y4 puts a skill rating on the card: the real payload satisfies the contract, and the two
regressions that matter — a block that moves the ranked gate, or one that stops matches being counted
so nothing gets earned — are caught.
"""
import pytest
import logic
import ratings
import cardstats


def test_live_contract_holds():
    assert cardstats.check() is True                    # the real guard, against the real payload


def test_moved_ranked_gate_is_caught(monkeypatch):
    # a later block "tunes" the provisional gate in ratings.py but not the frozen contract
    monkeypatch.setattr(ratings, "MIN_MATCHES", 3)
    with pytest.raises(ValueError, match="ranked gate"):
        cardstats.check()


def test_uncounted_play_earns_nothing_is_caught(monkeypatch):
    # a refactor breaks approval so matches never reach 'counted' — the earned card would stay empty
    monkeypatch.setattr(logic, "approve", lambda con, mid, pid: None)
    with pytest.raises(ValueError, match="winner card"):
        cardstats.check()
