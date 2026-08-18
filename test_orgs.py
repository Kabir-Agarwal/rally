"""Org / club accounts (SPEC Y3 — ADD org/club accounts).

Proves the engine the org/club feature-block is built on: the account-profile trust guards (name,
public @handle, kind) and the role graph OWNER > ADMIN > MEMBER with its one protected invariant —
an account always has exactly one owner (found seeds it, transfer moves it, nothing removes it).
"""
import pytest

import orgs as O


def test_check_holds():
    assert O.check() is True                                        # the real engine self-check


def test_account_profile_guards_and_normalizes():
    assert O.account("  Baseline TC  ", "@Baseline_TC", O.ORG) == {
        "name": "Baseline TC", "handle": "baseline_tc", "kind": O.ORG}
    assert O.account("X", "smash")["kind"] == O.CLUB               # kind defaults to club
    for bad in (lambda: O.account("  ", "smash"),                  # whitespace-only name
                lambda: O.account("", "smash"),                    # empty name
                lambda: O.account("Ok", "ab"),                     # handle too short
                lambda: O.account("Ok", "a b"),                    # handle has a space
                lambda: O.account("Ok", "smash!"),                 # handle bad charset
                lambda: O.account("Ok", "x" * 31),                 # handle too long
                lambda: O.account("Ok", "smash", "league")):       # unknown kind
        with pytest.raises(ValueError):
            bad()


def test_found_seats_the_sole_owner():
    m = [O.found("c1", 1)]
    assert m[0] == {"org": "c1", "player": 1, "role": O.OWNER}
    assert O.role_of("c1", 1, m) == O.OWNER and O.role_of("c1", 9, m) is None
    assert O.is_member("c1", 1, m) and not O.is_member("c1", 9, m)
    assert O.can_manage("c1", 1, m)
    assert O.owners("c1", m) == [1]


def test_add_admits_a_member_and_guards():
    m = [O.found("c1", 1)]
    joined = O.add("c1", 1, 2, m)                                   # owner admits 2 as a MEMBER
    assert joined == {"org": "c1", "player": 2, "role": O.MEMBER}
    m2 = m + [joined]
    assert not O.can_manage("c1", 2, m2)                            # a plain member does not manage
    for bad in (lambda: O.add("c1", 2, 3, m2),                     # a member cannot add
                lambda: O.add("c1", 7, 3, m2),                     # a stranger cannot add
                lambda: O.add("c1", 1, 2, m2)):                    # 2 already a member
        with pytest.raises(ValueError):
            bad()


def test_set_role_is_owner_only_and_cannot_touch_ownership():
    m = [O.found("c1", 1), {"org": "c1", "player": 2, "role": O.MEMBER}]
    up = O.set_role("c1", 1, 2, O.ADMIN, m)
    assert up == {"org": "c1", "player": 2, "role": O.ADMIN}
    m2 = [up if x["player"] == 2 else x for x in m]
    assert O.can_manage("c1", 2, m2)                                # promoted admin now manages
    assert O.set_role("c1", 1, 2, O.MEMBER, m2)["role"] == O.MEMBER  # ...and can be demoted
    for bad in (lambda: O.set_role("c1", 2, 1, O.MEMBER, m2),      # an admin cannot set roles
                lambda: O.set_role("c1", 1, 2, O.OWNER, m2),       # cannot grant OWNER here
                lambda: O.set_role("c1", 1, 9, O.ADMIN, m2),       # not a member
                lambda: O.set_role("c1", 1, 1, O.MEMBER, m2)):     # cannot demote the owner
        with pytest.raises(ValueError):
            bad()


def test_remove_self_leave_strict_rank_and_protected_owner():
    trio = [O.found("c1", 1), {"org": "c1", "player": 2, "role": O.ADMIN},
            {"org": "c1", "player": 3, "role": O.MEMBER}, {"org": "c1", "player": 4, "role": O.MEMBER}]
    assert [x["player"] for x in O.remove("c1", 3, 3, trio)] == [1, 2, 4]   # self-leave
    assert [x["player"] for x in O.remove("c1", 2, 3, trio)] == [1, 2, 4]   # admin removes a member
    assert len(trio) == 4                                           # input untouched (returns a copy)
    for bad in (lambda: O.remove("c1", 3, 2, trio),               # member cannot remove an admin
                lambda: O.remove("c1", 3, 4, trio),               # member cannot remove a peer
                lambda: O.remove("c1", 2, 1, trio),               # admin cannot remove the owner
                lambda: O.remove("c1", 1, 1, trio),               # the owner cannot leave
                lambda: O.remove("c1", 1, 9, trio)):              # not a member
        with pytest.raises(ValueError):
            bad()


def test_transfer_is_the_only_way_owner_moves():
    pair = [O.found("c1", 1), {"org": "c1", "player": 2, "role": O.ADMIN}]
    handed = O.transfer("c1", 1, 2, pair)
    assert {(x["player"], x["role"]) for x in handed} == {(1, O.ADMIN), (2, O.OWNER)}
    after = [handed[0] if x["player"] == 1 else handed[1] for x in pair]
    assert O.owners("c1", after) == [2]                            # still exactly one owner, now 2
    for bad in (lambda: O.transfer("c1", 2, 1, pair),             # 2 is not the owner
                lambda: O.transfer("c1", 1, 9, pair),             # 9 is not a member
                lambda: O.transfer("c1", 1, 1, pair)):            # already the owner
        with pytest.raises(ValueError):
            bad()


def test_reads_roster_order_and_orgs_of():
    club = [{"org": "c1", "player": 3, "role": O.MEMBER}, O.found("c1", 1),
            {"org": "c1", "player": 2, "role": O.ADMIN}, {"org": "c2", "player": 1, "role": O.MEMBER}]
    assert [x["player"] for x in O.roster("c1", club)] == [1, 2, 3]   # owner, admin, member
    assert O.orgs_of(1, club) == {"c1": O.OWNER, "c2": O.MEMBER}
