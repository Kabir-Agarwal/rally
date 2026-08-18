"""Nearby players — 50 km discovery + Connect (SPEC Y3 — ADD nearby players).

Proves the engine the nearby feature-block is built on: a haversine radius that is correct across the
curve of the Earth and the antimeridian, a 50 km filter that excludes anyone who can't be a nearby
stranger, and a Connect request lifecycle (pending -> accepted) in the friendships shape.
"""
import pytest

import nearby as N


def test_check_holds():
    assert N.check() is True                                       # the real engine self-check


def test_haversine_known_distances():
    assert N.haversine_km(0, 0, 0, 0) == pytest.approx(0, abs=1e-6)
    assert N.haversine_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.5)   # 1deg lng at the equator
    assert N.haversine_km(0, 0, 1, 0) == pytest.approx(111.2, abs=0.5)   # 1deg lat
    assert N.haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(343.5, abs=3.0)  # LON-PAR


def test_antimeridian_is_one_degree_not_three_fifty_nine():
    # 179.5degE to 179.5degW is 1deg apart (~111 km), not 359deg — the flat-subtraction bug is ~39,849 km.
    d = N.haversine_km(0, 179.5, 0, -179.5)
    assert d == pytest.approx(111.2, abs=0.5)
    assert d < 1000


def test_fifty_km_filter_excludes_self_hidden_nowhere_blocked():
    me = {"id": 1, "lat": 0.0, "lng": 0.0}
    players = [
        {"id": 2, "lat": 0.0, "lng": 0.30, "discoverable": True},   # ~33 km  -> in
        {"id": 3, "lat": 0.0, "lng": 0.10, "discoverable": True},   # ~11 km  -> in (nearest)
        {"id": 4, "lat": 0.0, "lng": 0.60, "discoverable": True},   # ~67 km  -> out
        {"id": 1, "lat": 0.0, "lng": 0.00, "discoverable": True},   # me      -> excluded
        {"id": 5, "lat": 0.0, "lng": 0.05, "discoverable": False},  # hidden  -> excluded
        {"id": 6, "lat": None, "lng": None, "discoverable": True},  # no loc  -> excluded
        {"id": 7, "lat": 0.0, "lng": 0.02, "discoverable": True},   # blocked -> excluded
    ]
    got = N.nearby(me, players, blocked={7})
    assert [p["id"] for p in got] == [3, 2]                         # nearest-first, everything else out
    assert 10 < got[0]["distance_km"] < 12                          # id 3 ~ 11.1 km


def test_radius_boundary_inclusive():
    me = {"id": 1, "lat": 0, "lng": 0}
    assert len(N.nearby(me, [{"id": 9, "lat": 0, "lng": 0.44, "discoverable": True}])) == 1   # ~49 km
    assert len(N.nearby(me, [{"id": 9, "lat": 0, "lng": 0.46, "discoverable": True}])) == 0   # ~51 km


def test_nearby_needs_my_location_and_positive_radius():
    with pytest.raises(ValueError):
        N.nearby({"id": 1}, [])                                     # no "near me" from nowhere
    with pytest.raises(ValueError):
        N.nearby({"id": 1, "lat": 0, "lng": 0}, [], radius_km=0)


def test_pair_key_is_canonical():
    assert N.pair_key(2, 1) == N.pair_key(1, 2) == (1, 2)


def test_connect_makes_pending_edge_and_relations():
    assert N.relation(1, 2, []) == N.NONE
    e = N.connect(1, 2, [])
    assert e == {"a": 1, "b": 2, "status": N.PENDING, "requested_by": 1}
    assert N.relation(1, 2, [e]) == N.OUTGOING                      # I asked
    assert N.relation(2, 1, [e]) == N.INCOMING                      # they were asked


def test_connect_refuses_self_and_duplicates():
    e = N.connect(1, 2, [])
    for a, b, edges in [(1, 1, []), (1, 2, [e]), (2, 1, [e])]:
        with pytest.raises(ValueError):
            N.connect(a, b, edges)


def test_accept_connects_and_refuses_illegal():
    e = N.connect(1, 2, [])
    a = N.accept(2, 1, [e])
    assert a["status"] == N.ACCEPTED
    assert N.relation(1, 2, [a]) == N.relation(2, 1, [a]) == N.CONNECTED
    with pytest.raises(ValueError):
        N.accept(1, 2, [e])                                        # can't accept your OWN request
    with pytest.raises(ValueError):
        N.accept(3, 4, [])                                         # nothing to accept
    with pytest.raises(ValueError):
        N.accept(2, 1, [a])                                        # already connected


def test_discover_tags_each_row_with_button_state():
    me = {"id": 1, "lat": 0.0, "lng": 0.0}
    edges = [{"a": 1, "b": 2, "status": N.PENDING, "requested_by": 2},   # incoming for me
             {"a": 1, "b": 3, "status": N.ACCEPTED, "requested_by": 1}]  # connected
    field = [{"id": 2, "lat": 0.0, "lng": 0.10, "discoverable": True},
             {"id": 3, "lat": 0.0, "lng": 0.20, "discoverable": True},
             {"id": 4, "lat": 0.0, "lng": 0.30, "discoverable": True}]
    rows = N.discover(me, field, edges)
    assert [(r["id"], r["relation"]) for r in rows] == [(2, N.INCOMING), (3, N.CONNECTED), (4, N.NONE)]
