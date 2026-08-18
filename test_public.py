"""Public layer (SPEC Y3 — ADD privacy controls, block/report, location-permission, the 16+ gate).

Proves the engine every earlier Y3 block deferred to (nearby / messenger / highlights / feed / orgs all
say "block/report, the 16+ gate, who-may-see-whom, location-permission are item #16"): the 16+ age gate,
the private-vs-public view policy, the block lifecycle with its symmetric effect + the blocked_ids
exclusion set the other engines take, the report trust guards, and the location-permission gate.
"""
from datetime import date

import pytest

import public as P


def test_check_holds():
    assert P.check() is True                                        # the real engine self-check


def test_age_gate_is_birthday_aware_and_leap_safe():
    today = date(2026, 8, 18)
    assert P.age_years(date(2010, 8, 18), today) == 16             # exactly 16 today
    assert P.age_years(date(2010, 8, 19), today) == 15             # birthday tomorrow -> still 15
    assert P.age_years(date(2008, 2, 29), date(2024, 3, 1)) == 16  # 29-Feb birthday, leap-safe
    assert P.is_old_enough(date(2010, 8, 18), today)               # 16 clears the gate
    assert not P.is_old_enough(date(2010, 8, 19), today)           # under 16 does not
    assert not P.is_old_enough(None, today)                        # unknown age fails closed
    assert P.require_age(date(2000, 1, 1), today) == 26            # returns the age when ok
    for bad in (lambda: P.require_age(date(2011, 8, 18), today),   # 15 -> raise
                lambda: P.require_age(None, today),                # unknown -> raise
                lambda: P.age_years("2000-01-01", today)):         # not a date -> raise
        with pytest.raises(ValueError):
            bad()


def test_can_view_self_block_private_public():
    assert P.can_view(1, 1, private=True, blocked=True)            # always see yourself
    assert not P.can_view(1, 2, blocked=True)                      # a block hides the target
    assert not P.can_view(1, 2, private=True, related=False)       # private + stranger -> hidden
    assert P.can_view(1, 2, private=True, related=True)            # private + relation -> visible
    assert P.can_view(1, 2)                                        # public + not blocked -> visible
    assert not P.can_view(1, 2, private=True, related=True, blocked=True)   # block beats a relation


def test_block_is_directed_but_symmetric_and_reversible():
    b = P.block(1, 2, [])
    assert b == {"blocker": 1, "blocked": 2}
    assert P.is_blocked(1, 2, [b]) and P.is_blocked(2, 1, [b])     # one-way block, mutual effect
    assert not P.is_blocked(1, 3, [b])
    for bad in (lambda: P.block(1, 1, []),                         # self
                lambda: P.block(1, 2, [b])):                       # same-direction duplicate
        with pytest.raises(ValueError):
            bad()
    two = [b, P.block(2, 1, [b])]                                  # reverse edge coexists
    lifted = P.unblock(1, 2, two)
    assert not any(x["blocker"] == 1 and x["blocked"] == 2 for x in lifted)
    assert P.is_blocked(1, 2, lifted)                              # 2->1 still stands
    assert len(two) == 2                                           # input untouched (copy returned)
    with pytest.raises(ValueError):
        P.unblock(1, 3, [b])                                       # nothing to lift


def test_blocked_ids_is_the_exclusion_set_the_engines_take():
    net = [{"blocker": 1, "blocked": 2}, {"blocker": 3, "blocked": 1}, {"blocker": 4, "blocked": 5}]
    assert P.blocked_ids(1, net) == {2, 3}                         # blocked-by-me + blocked-me
    assert P.blocked_ids(9, net) == set()                          # a stranger hides nobody


def test_report_guards_reason_kind_and_self():
    assert P.report(1, 2, "  spam  ", "message") == {
        "reporter": 1, "target": 2, "kind": "message", "reason": "spam"}
    assert P.report(1, 2, "harassment")["kind"] == "player"       # kind defaults to player
    for bad in (lambda: P.report(1, 1, "x"),                       # cannot report yourself (player)
                lambda: P.report(1, 2, "   "),                     # whitespace-only reason
                lambda: P.report(1, 2, ""),                        # empty reason
                lambda: P.report(1, 2, "x", "spaceship")):         # unknown kind
        with pytest.raises(ValueError):
            bad()


def test_can_discover_needs_granted_and_opt_in():
    assert P.can_discover(P.GRANTED, True)
    for perm, opt in [(P.GRANTED, False), (P.DENIED, True), (P.PROMPT, True), (P.DENIED, False)]:
        assert not P.can_discover(perm, opt)
    with pytest.raises(ValueError):
        P.can_discover("allowed", True)                            # not a W3C permission state
