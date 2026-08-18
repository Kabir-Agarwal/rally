"""Doubles-chemistry contract check (SPEC Y2 — KEEP doubles chemistry).

Proves the per-duo pair rating can't silently regress as Y3 features land on the rating pipeline:
the live engine satisfies the contract, and the two regressions that matter — a block that stops
rating duos, or one that quietly moves the provisional gate — are caught.
"""
import pytest
import ratings
import chemistry


def test_live_contract_holds():
    assert chemistry.check() is True                    # the real guard, against the real engine


def test_dropped_pair_rating_is_caught(monkeypatch):
    # a later block refactors the doubles path and stops rating the duo as a unit
    monkeypatch.setattr(ratings, "_apply_pair", lambda *a, **k: None)
    with pytest.raises(ValueError):
        chemistry.check()


def test_moved_provisional_gate_is_caught(monkeypatch):
    # a later block silently changes how many matches make a pair "established"
    monkeypatch.setattr(ratings, "PAIR_PROVISIONAL", chemistry.PROVISIONAL + 2)
    with pytest.raises(ValueError):
        chemistry.check()
