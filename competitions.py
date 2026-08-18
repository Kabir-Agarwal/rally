"""Competitions hub — Create / Manage / In-Queue / Scheduled over tournaments + leagues (SPEC Y3).

Y3 ADD: the competitions hub. Tournaments (tournaments.py) and leagues (leagues.py) each shipped a
proven ENGINE; this is the container that ties them together and gives a competition a LIFECYCLE and
a home on the hub's four sections:

    Create     — being set up; not yet open for entry                 (status: draft)
    In-Queue   — open for entrants; waiting to fill / get a date       (status: open)
    Scheduled  — field + start time locked; waiting to run             (status: scheduled)
    Manage     — running or finished; the owner advances / reviews it  (status: live, completed)

A competition is a plain dict (the same DB-free style as the sibling engines) that names a FORMAT
(tournament | league) and moves FORWARD through the lifecycle: draft -> open -> scheduled -> live ->
completed. bucket_of() sends each status to exactly one of the four sections, so hub() sorts any
list of competitions into the four screens the hub renders — and the four buckets always PARTITION
the input (every competition lands in exactly one section, none dropped or duplicated). start()
kicks a scheduled competition into play by dispatching its entrants to the right sub-engine — a
first-round bracket for a tournament, a full round-robin schedule for a league.

Persistence is deferred on purpose: the competitions table + the Create/Manage form wiring land with
the batched migrations (item #19, SPEC Y5 — no session applies schema). So the hub screen lands as
dummy UI now (SPEC Y1, blocks.py: competitions off -> dummy) with this engine proven behind it — the
exact sibling shape of items #7–#9.

check() walks a tournament and a league competition through the whole lifecycle, proves the four
sections partition every status, that illegal jumps fail loud, and that start() dispatches to the
right sub-engine — same fail-loud shape as the other preflight guards, wired into deploy.py.
"""
import tournaments
import leagues

# --- lifecycle statuses -----------------------------------------------------
DRAFT     = "draft"       # being created; not yet open for entry
OPEN      = "open"        # open for entrants; waiting to fill / be scheduled
SCHEDULED = "scheduled"   # field + start time locked; waiting to run
LIVE      = "live"        # in progress; the owner advances the bracket/standings
COMPLETED = "completed"   # finished; champion / final table decided
STATUSES  = (DRAFT, OPEN, SCHEDULED, LIVE, COMPLETED)
DEFAULT_STATUS = DRAFT    # a freshly-made competition with no status is a draft

# Forward-only lifecycle: a competition advances one step at a time, never skips or goes back.
TRANSITIONS = {
    DRAFT:     {OPEN},
    OPEN:      {SCHEDULED},
    SCHEDULED: {LIVE},
    LIVE:      {COMPLETED},
    COMPLETED: set(),      # terminal
}

# --- the four hub sections (SPEC Y3: Create / Manage / In-Queue / Scheduled) -
CREATE   = "create"
IN_QUEUE = "in_queue"
MANAGE   = "manage"
# The Scheduled section reuses SCHEDULED's string — a scheduled competition IS the Scheduled tab.
SECTIONS = (CREATE, IN_QUEUE, SCHEDULED, MANAGE)
BUCKET = {
    DRAFT:     CREATE,      # drafts live under Create
    OPEN:      IN_QUEUE,    # open-for-entry competitions are queued up
    SCHEDULED: SCHEDULED,   # scheduled competitions get their own section
    LIVE:      MANAGE,      # running competitions are managed
    COMPLETED: MANAGE,      # finished ones are reviewed under Manage
}

# --- competition formats: the tie to the two sub-engines --------------------
# Each format names the engine call that turns entrants into the initial live structure, plus that
# engine's own entrant bounds — a single source of truth, no magic numbers duplicated here.
FORMATS = {
    "tournament": {"label": "Tournament", "start": tournaments.first_round,
                   "min": tournaments.MIN_DRAW,  "max": tournaments.MAX_DRAW},
    "league":     {"label": "League",     "start": leagues.schedule,
                   "min": leagues.MIN_LEAGUE,    "max": leagues.MAX_LEAGUE},
}


def validate_format(fmt):
    """Trust-boundary guard: a competition's format must be one we know how to run."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown competition format {fmt!r} (want one of {tuple(FORMATS)})")
    return fmt


def normalize_status(status):
    """Trust-boundary guard: canonical status string. None/"" -> draft (a new competition); case and
    stray space tolerated (the value arrives from a UI); anything else raises — an unknown status is
    a bug to surface, never a competition silently mis-bucketed."""
    if status is None or status == "":
        return DEFAULT_STATUS
    s = str(status).strip().lower()
    if s not in STATUSES:
        raise ValueError(f"unknown competition status {status!r} (want one of {STATUSES}, or absent)")
    return s


def status_of(comp):
    """Canonical status of a competition dict — its "status" key normalized (absent -> draft)."""
    return normalize_status(comp.get("status"))


def bucket_of(status):
    """The hub section a status belongs to — one of the four SECTIONS. Total over STATUSES."""
    return BUCKET[normalize_status(status)]


def hub(competitions):
    """Sort competitions into the hub's four sections. Returns a dict keyed by SECTIONS, each a list
    in input order. The four buckets PARTITION the input: every competition lands in exactly one
    section, none dropped or duplicated — the invariant the hub screen relies on."""
    sections = {s: [] for s in SECTIONS}
    for c in competitions:
        sections[bucket_of(status_of(c))].append(c)
    return sections


def _require_schedulable(comp):
    """A competition can only be Scheduled once it has a start time AND a field size legal for its
    format (tournament 4–32, league 3–32) — you can't lock a dateless or unfillable competition."""
    if not comp.get("starts_at"):
        raise ValueError("a competition needs a start time before it can be Scheduled")
    fmt = FORMATS[validate_format(comp.get("format"))]
    n = len(comp.get("entrants") or [])
    if not (fmt["min"] <= n <= fmt["max"]):
        raise ValueError(f"{comp.get('format')} needs {fmt['min']}–{fmt['max']} entrants, got {n}")


def advance(comp, to):
    """Move a competition one step forward through its lifecycle, returning an UPDATED COPY — the
    caller's dict is untouched (pure). Refuses any illegal jump (fail loud), and refuses to Schedule
    a competition that has no start time or an illegal field size."""
    to = normalize_status(to)
    frm = status_of(comp)
    if to not in TRANSITIONS[frm]:
        legal = sorted(TRANSITIONS[frm]) or ["(none — terminal)"]
        raise ValueError(f"illegal transition {frm} -> {to} (from {frm} you can only go to {legal})")
    if to == SCHEDULED:
        _require_schedulable(comp)
    return {**comp, "status": to}


def start(comp):
    """Start a SCHEDULED competition: advance it to LIVE and build the initial live structure by
    dispatching its entrants to the format's engine. Returns (live_comp, structure) — structure is a
    first-round bracket (tournament) or a full round-robin schedule (league). advance() enforces that
    only a scheduled competition can start; the sub-engine re-validates the entrants. This is the hub
    driving both engines; persisting the structure is item #19's job."""
    live_comp = advance(comp, LIVE)                    # enforces scheduled -> live
    fmt = FORMATS[validate_format(comp.get("format"))]
    structure = fmt["start"](list(comp.get("entrants") or []))
    return live_comp, structure


def check():
    """Fail loud (ValueError) if the competitions hub engine regressed. Returns True when clean."""
    bad = []

    # 1. STATUS TRUST GUARD + DEFAULT — canonical statuses, case/space tolerance (a UI value), a new
    #    (status-less) competition reads as a draft, and anything unknown is refused.
    for good, want in [("draft", DRAFT), ("OPEN", OPEN), (" Scheduled ", SCHEDULED),
                       ("live", LIVE), ("completed", COMPLETED), (None, DRAFT), ("", DRAFT)]:
        if normalize_status(good) != want:
            bad.append(f"normalize_status({good!r}) = {normalize_status(good)!r}, want {want!r}")
    for junk in ("queued", "running", "done", "canceled", "1", "true"):
        try:
            normalize_status(junk)
            bad.append(f"normalize_status accepted an unknown status: {junk!r}")
        except ValueError:
            pass

    # 2. FOUR SECTIONS PARTITION EVERY STATUS — the four are exactly Create/In-Queue/Scheduled/Manage,
    #    every lifecycle status maps into one of them, and hub() drops/duplicates nothing.
    if set(SECTIONS) != {CREATE, IN_QUEUE, SCHEDULED, MANAGE}:
        bad.append(f"hub sections are {SECTIONS}, want Create/In-Queue/Scheduled/Manage")
    if {bucket_of(s) for s in STATUSES} - set(SECTIONS):
        bad.append("a lifecycle status maps to a section outside the four")
    comps = [{"id": i, "format": "league", "status": s} for i, s in enumerate(STATUSES)]
    comps.append({"id": 99, "format": "tournament"})     # no status -> draft -> Create
    sec = hub(comps)
    if sorted(sec) != sorted(SECTIONS):
        bad.append(f"hub() keys {sorted(sec)} are not the four sections")
    if sum(len(v) for v in sec.values()) != len(comps):
        bad.append("hub() dropped or duplicated a competition (partition leak)")
    if [c["id"] for c in sec[CREATE]] != [0, 99]:        # draft + the status-less one
        bad.append(f"Create section wrong: {[c['id'] for c in sec[CREATE]]}")
    if [c["id"] for c in sec[MANAGE]] != [3, 4]:         # live + completed
        bad.append(f"Manage section wrong: {[c['id'] for c in sec[MANAGE]]}")

    # 3. LEGAL LIFECYCLE — a competition walks draft->open->scheduled->live->completed, each step
    #    returning an updated COPY (the source dict untouched). Illegal jumps fail loud.
    src = {"format": "tournament", "entrants": [f"P{i}" for i in range(6)], "starts_at": "2026-09-01T10:00Z",
           "status": DRAFT}
    c = src
    for step in (OPEN, SCHEDULED, LIVE, COMPLETED):
        c = advance(c, step)
        if c["status"] != step:
            bad.append(f"advance to {step} did not set the status")
    if src["status"] != DRAFT:
        bad.append("advance() mutated the caller's competition dict (must return a copy)")
    for frm, to in [(DRAFT, SCHEDULED), (DRAFT, LIVE), (OPEN, LIVE), (SCHEDULED, COMPLETED),
                    (LIVE, OPEN), (COMPLETED, LIVE)]:
        try:
            advance(dict(src, status=frm), to)
            bad.append(f"advance allowed an illegal jump {frm} -> {to}")
        except ValueError:
            pass

    # 4. SCHEDULING GUARDS — you cannot Schedule a competition with no start time or an illegal field
    #    size (tournament 4–32, league 3–32).
    for comp in ({"format": "tournament", "entrants": [f"P{i}" for i in range(6)], "status": OPEN},  # no date
                 {"format": "tournament", "entrants": ["A", "B"], "starts_at": "t", "status": OPEN}):  # 2 < 4
        try:
            advance(comp, SCHEDULED)
            bad.append(f"scheduled a competition it should have refused: {comp}")
        except ValueError:
            pass

    # 5. START DISPATCHES TO THE RIGHT SUB-ENGINE — starting a scheduled competition advances it to
    #    live and builds the initial live structure: a first-round bracket for a tournament, a full
    #    round-robin schedule for a league. This is the hub driving both engines.
    ents6 = [f"P{i}" for i in range(6)]
    live_t, draw = start({"format": "tournament", "entrants": ents6, "starts_at": "t", "status": SCHEDULED})
    if live_t["status"] != LIVE:
        bad.append("start() did not advance the tournament to live")
    if draw != tournaments.first_round(ents6):
        bad.append("start() did not build the tournament first round via the engine")
    ents5 = [f"P{i}" for i in range(5)]
    _, sch = start({"format": "league", "entrants": ents5, "starts_at": "t", "status": SCHEDULED})
    if sch != leagues.schedule(ents5):
        bad.append("start() did not build the league schedule via the engine")
    try:
        start({"format": "league", "entrants": ents5, "status": OPEN})   # not scheduled
        bad.append("start() ran on a competition that wasn't scheduled")
    except ValueError:
        pass

    # 6. FORMAT TRUST GUARD — an unknown format is refused at the boundary.
    for op in (lambda: validate_format("padel"),
               lambda: start({"format": "padel", "entrants": [1, 2, 3, 4], "status": SCHEDULED})):
        try:
            op()
            bad.append("an unknown competition format passed the guard")
        except ValueError:
            pass

    if bad:
        raise ValueError("competitions hub engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"competitions OK: formats {tuple(FORMATS)}, lifecycle {STATUSES}, sections {SECTIONS}")
