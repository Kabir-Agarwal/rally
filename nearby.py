"""Nearby players — a 50 km discovery radius + Connect (SPEC Y3).

Y3 ADD: nearby players (50 km + Connect). Two halves, both pure:

  50 km   — given WHERE you are and a list of players who have opted to be discoverable, list the
            ones within a radius (50 km by the spec), nearest first, each tagged with how far away
            they are. Distance is the great-circle (haversine) distance, so it is correct across the
            curve of the Earth and the antimeridian — not a flat lat/lng subtraction that explodes
            near ±180°.
  Connect — from that list you can Connect with a stranger: send a request they can accept. A
            connection is one unordered pair with a status (pending -> accepted), the exact shape of
            the already-proposed `friendships` table in the identity-foundation migration
            (a_id < b_id, status, requested_by). relation() tells the screen which button to show
            (Connect / Requested / Accept / Connected).

This is the pure ENGINE the nearby feature-block is built on — deliberately DB-free and dependency-
free, the same shape as tournaments.py / leagues.py / practice.py / competitions.py. Persistence is
deferred on purpose: player location (lat, lng, discoverable opt-in) and the connections/friendships
table land with the batched migrations (item #19, SPEC Y5 — no session applies schema); the map +
Connect button wiring land on the screen. So the Nearby screen lands as dummy UI now (SPEC Y1,
blocks.py: nearby off -> dummy) with this engine proven and preflight-gated behind it.

Privacy/permission are the public layer's job (item #16 — location-permission handling, block/report,
16+ gate). The engine only assumes the two things nearby cannot exist without: a player must have a
location AND have opted in (`discoverable`) to appear at all, and an optional `blocked` set is
excluded — one parameter, so item #16 wires block/report in without a rewrite.

Model — plain dicts, no DB (ids are anything hashable+comparable — the app's player ids are ints):
  player  — {"id", "lat", "lng", "discoverable": bool, ...}; other keys (name, rating) pass through
            untouched. lat/lng None (or discoverable false) = not on the map.
  edge    — {"a", "b", "status", "requested_by"}; a<b canonical (friendships shape). status one of
            'pending' | 'accepted'. relation(me, them, edges) collapses an edge to this viewer's
            button state: 'none' | 'outgoing' | 'incoming' | 'connected'.

check() proves the haversine against known distances (incl. the antimeridian), the 50 km filter
(self / hidden / located-nowhere / blocked all excluded, nearest-first), and the whole Connect
lifecycle — same fail-loud shape as the sibling engines, wired into deploy.py preflight.
"""
from math import radians, sin, cos, asin, sqrt

DEFAULT_RADIUS_KM = 50.0          # SPEC Y3: nearby players within 50 km
EARTH_KM = 6371.0088              # mean Earth radius (IUGG), the haversine constant

# --- connection statuses (stored) — match the friendships CHECK in the identity migration ----
PENDING = "pending"
ACCEPTED = "accepted"
STATUSES = (PENDING, ACCEPTED)

# --- relation: an edge as THIS viewer sees it — the four Connect-button states ---------------
NONE = "none"          # no edge — show "Connect"
OUTGOING = "outgoing"  # I requested, waiting on them — show "Requested"
INCOMING = "incoming"  # they requested me — show "Accept"
CONNECTED = "connected"  # accepted both ways — show "Connected"
RELATIONS = (NONE, OUTGOING, INCOMING, CONNECTED)


def valid_coords(lat, lng):
    """A usable location: both present and in range (lat -90..90, lng -180..180)."""
    return (lat is not None and lng is not None
            and -90 <= lat <= 90 and -180 <= lng <= 180)


def _require_coords(lat, lng, who):
    """Trust-boundary guard: a real, in-range location (coords arrive from a browser geolocation)."""
    if not valid_coords(lat, lng):
        raise ValueError(f"{who} has no valid location: lat={lat!r} lng={lng!r} "
                         f"(want lat -90..90, lng -180..180)")


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km between two points. Correct across curvature AND the antimeridian
    (the trig on the longitude delta wraps naturally — 179.5° to -179.5° is 1° apart, not 359°)."""
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(h))


def nearby(me, players, radius_km=DEFAULT_RADIUS_KM, blocked=()):
    """Players within `radius_km` of `me`, nearest first, each a COPY with a "distance_km" (1-dp).

    Excludes, silently, anyone who cannot honestly be a nearby stranger to connect with: yourself
    (same id), anyone in `blocked`, anyone not `discoverable` (opt-in), and anyone with no valid
    location (you can't place them on the map). `me` MUST have a valid location — you can't compute
    "near me" from nowhere, so that's a fail-loud caller error, not an empty list."""
    if radius_km <= 0:
        raise ValueError(f"radius_km must be positive, got {radius_km!r}")
    _require_coords(me.get("lat"), me.get("lng"), "me")
    me_id, blocked = me.get("id"), set(blocked)
    out = []
    for p in players:
        pid = p.get("id")
        if pid == me_id or pid in blocked or not p.get("discoverable"):
            continue
        if not valid_coords(p.get("lat"), p.get("lng")):
            continue
        d = haversine_km(me["lat"], me["lng"], p["lat"], p["lng"])
        if d <= radius_km:                       # true distance for the cutoff; round only for display
            out.append({**p, "distance_km": round(d, 1)})
    out.sort(key=lambda p: (p["distance_km"], p["id"]))   # nearest first, id tiebreak = stable order
    return out


# --- Connect ---------------------------------------------------------------------------------
def pair_key(a, b):
    """Canonical unordered pair (a < b) — the friendships primary key, so one row per pair however
    the two ids are passed in. Ids must be comparable (the app's are ints)."""
    return tuple(sorted((a, b)))


def _index(edges):
    """{pair_key: edge} for O(1) lookup of the connection between any two players."""
    return {pair_key(e["a"], e["b"]): e for e in edges}


def _relation(me, edge):
    """One edge (or None) as `me`'s button state — the single source of truth for the four states."""
    if edge is None:
        return NONE
    if edge["status"] == ACCEPTED:
        return CONNECTED
    return OUTGOING if edge.get("requested_by") == me else INCOMING


def relation(me, them, edges):
    """How `me` relates to `them`: 'none' | 'outgoing' | 'incoming' | 'connected' — what button the
    Nearby screen shows next to that player."""
    return _relation(me, _index(edges).get(pair_key(me, them)))


def connect(me, them, edges):
    """`me` sends a connection request to `them`. Returns a NEW pending edge (the caller persists it);
    `edges` is untouched. Fails loud on connecting to yourself or when any edge already exists
    (pending or accepted) — the pair is unique, so a duplicate is a bug to surface, not a silent no-op."""
    if me == them:
        raise ValueError("cannot connect to yourself")
    if _index(edges).get(pair_key(me, them)) is not None:
        raise ValueError(f"a connection between {me!r} and {them!r} already exists")
    a, b = pair_key(me, them)
    return {"a": a, "b": b, "status": PENDING, "requested_by": me}


def accept(me, them, edges):
    """`me` accepts `them`'s pending request. Returns the UPDATED (accepted) edge; `edges` untouched.
    Fails loud if there is no request, it's already accepted, or `me` is trying to accept their OWN
    request (only the other party can accept)."""
    edge = _index(edges).get(pair_key(me, them))
    if edge is None:
        raise ValueError(f"no connection request between {me!r} and {them!r} to accept")
    if edge["status"] == ACCEPTED:
        raise ValueError("already connected")
    if edge.get("requested_by") == me:
        raise ValueError("cannot accept your own request — the other player accepts it")
    return {**edge, "status": ACCEPTED}


def discover(me, players, edges=(), radius_km=DEFAULT_RADIUS_KM, blocked=()):
    """The one call the Nearby screen makes: the 50 km list, each row also tagged with `relation` (the
    Connect-button state) from the connection `edges`. This is the two halves joined — nearby() finds
    them, relation() says how you already stand with each — the way competitions.hub() ties its
    engines together. Rows stay in nearest-first order."""
    idx = _index(edges)
    me_id = me.get("id")
    rows = nearby(me, players, radius_km=radius_km, blocked=blocked)
    for r in rows:
        r["relation"] = _relation(me_id, idx.get(pair_key(me_id, r["id"])))
    return rows


def check():
    """Fail loud (ValueError) if the nearby-players engine regressed. Returns True when clean."""
    bad = []

    # 1. COORDINATE TRUST GUARD — a location is two in-range numbers; anything else is not on the map.
    for lat, lng, ok in [(0, 0, True), (90, 180, True), (-90, -180, True), (51.5, -0.12, True),
                         (None, 0, False), (0, None, False), (91, 0, False), (0, 181, False),
                         (-91, 0, False), (0, -181, False)]:
        if valid_coords(lat, lng) != ok:
            bad.append(f"valid_coords({lat},{lng}) = {valid_coords(lat, lng)}, want {ok}")
    for op in (lambda: nearby({"id": 1}, []),                      # me has no location -> raise
               lambda: nearby({"id": 1, "lat": 0, "lng": 0}, [], radius_km=0)):   # radius must be >0
        try:
            op()
            bad.append("nearby accepted an invalid me / radius")
        except ValueError:
            pass

    # 2. HAVERSINE vs KNOWN DISTANCES — identical points are 0; one degree (lat or lng at the equator)
    #    is ~111.2 km; London->Paris is ~343 km (proves curvature); and the antimeridian is handled —
    #    179.5°E to 179.5°W is 1° (~111 km) apart, NOT 359° (~39,849 km) as a flat subtraction gives.
    def approx(got, want, tol, label):
        if abs(got - want) > tol:
            bad.append(f"haversine {label}: got {got:.2f}, want ~{want} (+/-{tol})")
    approx(haversine_km(0, 0, 0, 0), 0, 1e-6, "identical")
    approx(haversine_km(0, 0, 0, 1), 111.2, 0.5, "1deg-lng-equator")
    approx(haversine_km(0, 0, 1, 0), 111.2, 0.5, "1deg-lat")
    approx(haversine_km(51.5074, -0.1278, 48.8566, 2.3522), 343.5, 3.0, "london-paris")
    antimeridian = haversine_km(0, 179.5, 0, -179.5)
    approx(antimeridian, 111.2, 0.5, "antimeridian")
    if antimeridian > 1000:                                       # the flat-subtraction bug would be huge
        bad.append(f"antimeridian distance {antimeridian:.0f} km — longitude wrap is broken")

    # 3. THE 50 km FILTER — from (0,0): inside is kept, outside dropped, and self / not-discoverable /
    #    no-location / blocked are all excluded. Rows come back nearest-first with a distance_km.
    me = {"id": 1, "lat": 0.0, "lng": 0.0}
    players = [
        {"id": 2, "lat": 0.0, "lng": 0.30, "discoverable": True},   # ~33 km  -> in
        {"id": 3, "lat": 0.0, "lng": 0.10, "discoverable": True},   # ~11 km  -> in (nearest)
        {"id": 4, "lat": 0.0, "lng": 0.60, "discoverable": True},   # ~67 km  -> out (> 50)
        {"id": 1, "lat": 0.0, "lng": 0.00, "discoverable": True},   # me      -> excluded
        {"id": 5, "lat": 0.0, "lng": 0.05, "discoverable": False},  # hidden  -> excluded
        {"id": 6, "lat": None, "lng": None, "discoverable": True},  # no loc  -> excluded
        {"id": 7, "lat": 0.0, "lng": 0.02, "discoverable": True},   # ~2 km   -> blocked out
    ]
    got = nearby(me, players, blocked={7})
    if [p["id"] for p in got] != [3, 2]:                           # 11 km before 33 km, rest excluded
        bad.append(f"50 km filter/order wrong: {[p['id'] for p in got]}, want [3, 2]")
    if got and "distance_km" not in got[0]:
        bad.append("nearby row has no distance_km")
    if got and not (10 < got[0]["distance_km"] < 12):              # id 3 ~ 11.1 km
        bad.append(f"nearest distance_km looks wrong: {got[0]['distance_km']}")
    # boundary: a player exactly at the radius is included (<=), just past it is not.
    edge_in = nearby({"id": 1, "lat": 0, "lng": 0},
                     [{"id": 9, "lat": 0, "lng": 0.44, "discoverable": True}])   # ~49 km
    edge_out = nearby({"id": 1, "lat": 0, "lng": 0},
                      [{"id": 9, "lat": 0, "lng": 0.46, "discoverable": True}])  # ~51 km
    if len(edge_in) != 1 or len(edge_out) != 0:
        bad.append("radius boundary is off (inside kept / outside dropped)")

    # 4. CONNECT LIFECYCLE — pair is canonical (order-independent); the four relation states; connect()
    #    makes a pending edge and refuses self + duplicates; accept() flips to connected and refuses
    #    accepting your own request / a non-existent / an already-accepted one.
    if pair_key(2, 1) != (1, 2) or pair_key(1, 2) != (1, 2):
        bad.append("pair_key is not canonical (a<b)")
    if relation(1, 2, []) != NONE:
        bad.append("no edge should read as 'none'")
    e = connect(1, 2, [])
    if e != {"a": 1, "b": 2, "status": PENDING, "requested_by": 1}:
        bad.append(f"connect built the wrong edge: {e}")
    if relation(1, 2, [e]) != OUTGOING or relation(2, 1, [e]) != INCOMING:
        bad.append("pending edge should be outgoing for the requester, incoming for the other")
    for op in (lambda: connect(1, 1, []),                          # self
               lambda: connect(1, 2, [e]),                         # duplicate
               lambda: connect(2, 1, [e])):                        # duplicate, other direction
        try:
            op()
            bad.append("connect allowed a self/duplicate connection")
        except ValueError:
            pass
    a = accept(2, 1, [e])
    if a["status"] != ACCEPTED:
        bad.append("accept did not mark the edge connected")
    if relation(1, 2, [a]) != CONNECTED or relation(2, 1, [a]) != CONNECTED:
        bad.append("an accepted edge should read 'connected' both ways")
    for op in (lambda: accept(1, 2, [e]),                          # accepting your OWN request
               lambda: accept(3, 4, []),                           # nothing to accept
               lambda: accept(2, 1, [a])):                         # already accepted
        try:
            op()
            bad.append("accept allowed an illegal accept")
        except ValueError:
            pass

    # 5. DISCOVER JOINS BOTH HALVES — the 50 km list, each row tagged with its Connect-button state.
    #    me(1): 2 sent me a request (incoming), I'm connected to 3, 4 is a fresh stranger (none).
    edges = [{"a": 1, "b": 2, "status": PENDING, "requested_by": 2},   # 2 -> 1 : incoming for me
             {"a": 1, "b": 3, "status": ACCEPTED, "requested_by": 1}]  # connected
    field = [{"id": 2, "lat": 0.0, "lng": 0.10, "discoverable": True},   # ~11 km
             {"id": 3, "lat": 0.0, "lng": 0.20, "discoverable": True},   # ~22 km
             {"id": 4, "lat": 0.0, "lng": 0.30, "discoverable": True}]   # ~33 km
    rows = discover(me, field, edges)
    if [(r["id"], r["relation"]) for r in rows] != [(2, INCOMING), (3, CONNECTED), (4, NONE)]:
        bad.append(f"discover relations/order wrong: {[(r['id'], r['relation']) for r in rows]}")

    if bad:
        raise ValueError("nearby-players engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"nearby OK: {DEFAULT_RADIUS_KM:.0f} km haversine radius (antimeridian-safe), "
          f"Connect states {RELATIONS}")
