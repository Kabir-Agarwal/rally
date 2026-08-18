"""Delete-past-matches contract check (SPEC Y2 — KEEP delete-past-matches).

Proves the soft, reversible delete can't silently regress as Y3 features land on the match lifecycle
and rating pipeline: the live engine satisfies the contract, and the two regressions that matter — a
block that turns delete into a hard purge, or one that makes delete a no-op so a deleted past match
still counts toward ratings — are caught.
"""
import pytest
import logic
import deletion


def test_live_contract_holds():
    assert deletion.check() is True                     # the real guard, against the real engine


def test_hard_delete_is_caught(monkeypatch):
    # a later block "cleans up" by physically purging the row instead of tombstoning it
    def hard(con, mid):
        con.execute("DELETE FROM matches WHERE id=?", (mid,))
        con.commit()
        return "deleted"
    monkeypatch.setattr(logic, "delete_match", hard)
    with pytest.raises(ValueError):
        deletion.check()


def test_noop_delete_breaks_rollback(monkeypatch):
    # a refactor makes delete a no-op (wrong status / early return): the "deleted" past match still counts
    monkeypatch.setattr(logic, "delete_match", lambda con, mid: "deleted")
    with pytest.raises(ValueError, match="roll back"):
        deletion.check()
