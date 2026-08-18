"""Competitions hub engine (SPEC Y3 — ADD competitions hub: Create / Manage / In-Queue / Scheduled).

Proves the container that ties tournaments (tournaments.py) and leagues (leagues.py) together: a
competition has a lifecycle (draft -> open -> scheduled -> live -> completed), the four hub sections
partition every status, illegal jumps fail loud, and starting a competition dispatches to the right
sub-engine (a bracket for a tournament, a schedule for a league).
"""
import pytest

import competitions as C
import tournaments
import leagues


def test_check_holds():
    assert C.check() is True                                    # the real engine self-check


def test_four_sections_are_the_spec_four():
    assert set(C.SECTIONS) == {"create", "manage", "in_queue", "scheduled"}


def test_hub_partitions_every_competition_into_the_four_sections():
    comps = [{"id": i, "format": "league", "status": s} for i, s in enumerate(C.STATUSES)]
    comps.append({"id": 99, "format": "tournament"})            # no status -> draft
    sec = C.hub(comps)
    assert sorted(sec) == sorted(C.SECTIONS)
    assert sum(len(v) for v in sec.values()) == len(comps)      # nothing dropped or duplicated
    assert [c["id"] for c in sec["create"]] == [0, 99]          # drafts (incl. the status-less one)
    assert [c["id"] for c in sec["in_queue"]] == [1]            # open == queued up
    assert [c["id"] for c in sec["scheduled"]] == [2]
    assert [c["id"] for c in sec["manage"]] == [3, 4]           # live + completed


def test_status_default_and_trust_guard():
    assert C.status_of({}) == C.DRAFT                           # a new competition is a draft
    assert C.normalize_status(" Scheduled ") == C.SCHEDULED     # case/space tolerant (a UI value)
    for junk in ("queued", "running", "done", "1"):
        with pytest.raises(ValueError):
            C.normalize_status(junk)


def test_lifecycle_advances_one_step_and_is_pure():
    comp = {"format": "tournament", "entrants": [f"P{i}" for i in range(6)],
            "starts_at": "2026-09-01T10:00Z", "status": C.DRAFT}
    c = comp
    for step in (C.OPEN, C.SCHEDULED, C.LIVE, C.COMPLETED):
        c = C.advance(c, step)
        assert c["status"] == step
    assert comp["status"] == C.DRAFT                            # the source dict is never mutated


def test_illegal_jumps_and_schedule_guards_fail_loud():
    base = {"format": "tournament", "entrants": [f"P{i}" for i in range(6)], "starts_at": "t"}
    for frm, to in [("draft", "scheduled"), ("open", "live"), ("live", "open")]:
        with pytest.raises(ValueError):
            C.advance(dict(base, status=frm), to)
    with pytest.raises(ValueError):                             # no start time -> can't Schedule
        C.advance({"format": "tournament", "entrants": [f"P{i}" for i in range(6)], "status": "open"}, "scheduled")
    with pytest.raises(ValueError):                             # too few entrants -> can't Schedule
        C.advance({"format": "tournament", "entrants": ["A", "B"], "starts_at": "t", "status": "open"}, "scheduled")


def test_start_dispatches_to_the_right_sub_engine():
    ents = [f"P{i}" for i in range(6)]
    live_t, draw = C.start({"format": "tournament", "entrants": ents, "starts_at": "t", "status": "scheduled"})
    assert live_t["status"] == C.LIVE
    assert draw == tournaments.first_round(ents)               # a first-round bracket

    ents5 = [f"P{i}" for i in range(5)]
    _, sch = C.start({"format": "league", "entrants": ents5, "starts_at": "t", "status": "scheduled"})
    assert sch == leagues.schedule(ents5)                     # a full round-robin schedule

    with pytest.raises(ValueError):                           # only a scheduled competition can start
        C.start({"format": "league", "entrants": ents5, "status": "open"})


def test_unknown_format_refused():
    with pytest.raises(ValueError):
        C.validate_format("padel")
    with pytest.raises(ValueError):
        C.start({"format": "padel", "entrants": [1, 2, 3, 4], "status": "scheduled"})
