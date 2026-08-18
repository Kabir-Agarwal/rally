"""Public layer — privacy controls, block/report, location-permission, the 16+ gate (SPEC Y3).

Y3 ADD: the public layer. Every earlier Y3 engine (nearby / messenger / highlights / feed / orgs)
built its feature and deferred the SAME four things to here — "block/report, the 16+ gate,
who-may-see-whom, and location-permission handling are item #16". This is that consolidation: the one
place the app decides who may see, reach, be found by, or take part at all. Four pure parts:

  16+ gate      — Rally's public layer is 16+. age_years() is birthday-aware whole-year age (leap-safe);
                  is_old_enough() / require_age() gate participation. No clock in a pure engine: the
                  caller passes `today` (a date), the same "no clock, caller stamps" rule feed/messenger
                  follow for their timestamps.
  privacy       — an account is PUBLIC or PRIVATE. A private account is visible only to itself and to
                  people it is already related to (an accepted connection / an approved follower); the
                  world sees nothing. That is the one privacy control an account cannot exist without —
                  per-field visibility is gold-plating (skipped).
  block/report  — block(actor, other) is a directed edge (like feed.follow), but its EFFECT is symmetric:
                  is_blocked() is true in either direction, so a block hides both ways and cuts messaging
                  both ways. blocked_ids(me) is the exclusion set the other engines already take
                  (nearby(blocked=...), a feed filter) — the one-parameter tie-in each of them left for
                  the public layer. report(reporter, target, reason, kind) is a moderation record with a
                  real reason.
  location perm — can_discover(permission, opt_in): you appear in Nearby only if the browser GRANTED
                  geolocation AND you opted in. `permission` mirrors the W3C Permissions API state
                  ('prompt' | 'granted' | 'denied') — the real browser contract — so a 'denied' and the
                  not-yet-asked 'prompt' both mean no location, so off the map. This IS nearby's
                  per-player `discoverable` bit.

The one screen-level decision is can_view(viewer, target, private=, blocked=, related=): the POLICY,
given the FACTS the caller looks up from whichever graph applies (the block set, the privacy flag, the
relation). Messaging (messenger's deferred DM gating) and who-may-see-a-club read the same primitives —
a block forbids it, a private account only opens to a relation — so there is no second policy function
to drift out of sync. The age gate is the FRONT DOOR (account-level eligibility); can_view is per-pair.

Same shape as the sibling engines — DB-free, dependency-free (stdlib `datetime.date` only) — proven by
check() and wired into deploy.py preflight. Persistence is deferred on purpose: the columns
(accounts.visibility, players.dob, players.location_permission + discoverable) and the tables (blocks:
blocker, blocked — unique per direction; reports: reporter, target, kind, reason, at) land with the
batched migrations (item #19, SPEC Y5 — no session applies schema); the privacy toggle, the Block /
Report buttons, the blocked-users list, the location prompt and the age gate surface within the existing
Profile + each feature screen. The public layer is cross-cutting — it is NOT a new nav tab.

Model — plain dicts, no DB (ids are anything hashable+comparable — the app's player/account ids are ints):
  block   — {"blocker", "blocked"}. Directed (who blocked whom, so only the blocker can unblock), but
            is_blocked() checks BOTH directions — the effect is mutual. Unique per direction.
  report  — {"reporter", "target", "kind", "reason"}. kind names the reported surface; the caller
            stamps id + at.
  dob / today  — datetime.date. permission — one of PROMPT | GRANTED | DENIED. visibility — the caller
            holds PUBLIC | PRIVATE per account and passes `private=` into can_view.

check() proves the age math (leap-year birthday boundary + the 16 cutoff), the view policy (self /
block / private-vs-related / public), the block lifecycle (directed store, symmetric effect, the
exclusion set, unblock), the report guards, and the location-permission gate — same fail-loud shape as
the sibling engines, wired into deploy.py preflight.
"""
from datetime import date

MIN_AGE = 16                       # SPEC Y3: the public layer is 16+

# --- account visibility (the privacy control) ------------------------------------------------
PUBLIC = "public"
PRIVATE = "private"
VISIBILITIES = (PUBLIC, PRIVATE)

# --- browser geolocation permission — the W3C Permissions API states -------------------------
PROMPT = "prompt"          # not yet asked (or reset) — no location
GRANTED = "granted"        # the user allowed it — a location is available
DENIED = "denied"          # the user refused it — no location
PERMISSIONS = (PROMPT, GRANTED, DENIED)

# --- what a report can be filed against (the app's public surfaces) --------------------------
REPORTABLE = ("player", "post", "highlight", "message", "club")


# --- the 16+ gate ----------------------------------------------------------------------------
def age_years(dob, today):
    """Whole years lived from `dob` to `today` (both datetime.date). Birthday-aware and leap-safe:
    someone born 29 Feb 2008 turns 16 on 1 Mar 2024, not 28 Feb. No clock here — the caller passes
    `today`, the same "no clock in a pure engine" rule feed/messenger follow for their timestamps."""
    if not isinstance(dob, date) or not isinstance(today, date):
        raise ValueError("age_years needs datetime.date for dob and today")
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def is_old_enough(dob, today, min_age=MIN_AGE):
    """True if `dob` is at least `min_age` years before `today` — the 16+ gate. A missing dob is NOT
    old enough: unknown age fails closed."""
    return dob is not None and age_years(dob, today) >= min_age


def require_age(dob, today, min_age=MIN_AGE):
    """The trust boundary the app calls before it lets an account onto the public layer. Fails loud
    unless `dob` clears the `min_age` gate (under-age, or unknown age, raises); returns the age when ok."""
    if not is_old_enough(dob, today, min_age):
        raise ValueError(f"must be at least {min_age} to use the public layer (16+ gate)")
    return age_years(dob, today)


# --- privacy: the view policy (the one screen-level decision) ---------------------------------
def can_view(viewer, target, private=False, blocked=False, related=False):
    """Can `viewer` see `target`'s public identity/content? The POLICY; the caller supplies the FACTS
    (is the target account `private`? is the pair `blocked`? is the viewer a `related` connection /
    approved follower?) from whichever graph applies — the way nearby takes a `blocked` set.

      - you always see yourself                    (viewer == target)
      - a block hides both ways, overriding all    (blocked -> never)
      - a PRIVATE account opens only to a relation (related -> yes, else no)
      - a PUBLIC account opens to anyone not blocked

    Messaging (messenger's DM gating) and who-may-see-a-club read the same rule, so there is no second
    policy to drift. The age gate is separate — it is the front door, this is per-pair."""
    if viewer == target:
        return True
    if blocked:
        return False
    if private:
        return related
    return True


# --- block / report --------------------------------------------------------------------------
def block(actor, other, blocks):
    """`actor` blocks `other`. Returns a NEW directed edge {"blocker", "blocked"} (the caller persists
    it); `blocks` is untouched. Directed so only the blocker can lift it, but the EFFECT is symmetric
    (is_blocked checks both ways). Fails loud on blocking yourself or a same-direction duplicate — one
    row per (blocker, blocked), like feed.follow."""
    if actor == other:
        raise ValueError("cannot block yourself")
    if any(b["blocker"] == actor and b["blocked"] == other for b in blocks):
        raise ValueError(f"{actor!r} already blocks {other!r}")
    return {"blocker": actor, "blocked": other}


def unblock(actor, other, blocks):
    """`actor` lifts their block on `other`. Returns a NEW blocks list without that directed edge;
    `blocks` untouched. Only the blocker can unblock — the reverse edge (if `other` also blocked
    `actor`) stays. Fails loud if `actor` was not blocking `other`: nothing to lift."""
    if not any(b["blocker"] == actor and b["blocked"] == other for b in blocks):
        raise ValueError(f"{actor!r} is not blocking {other!r}")
    return [b for b in blocks if not (b["blocker"] == actor and b["blocked"] == other)]


def is_blocked(a, b, blocks):
    """True if either `a` blocked `b` or `b` blocked `a` — the block effect is mutual, so this is what
    view / message / discovery all read to hide the pair from each other."""
    return any((x["blocker"], x["blocked"]) in ((a, b), (b, a)) for x in blocks)


def blocked_ids(me, blocks):
    """Everyone hidden from `me`: those `me` blocked, AND those who blocked `me`. This is the exclusion
    set the other engines already accept — nearby(me, players, blocked=blocked_ids(me, blocks)), a feed
    filter — the one-parameter tie-in each of them left for the public layer to fill."""
    return ({b["blocked"] for b in blocks if b["blocker"] == me}
            | {b["blocker"] for b in blocks if b["blocked"] == me})


def report(reporter, target, reason, kind="player"):
    """File a moderation report (the caller stamps its id + at and persists it). Trust boundary: `reason`
    arrives from a user -> non-empty, stored stripped (like feed.post / messenger.compose); `kind` names
    a real reportable surface; and you cannot report your own player row. Returns
    {"reporter", "target", "kind", "reason"}."""
    if kind not in REPORTABLE:
        raise ValueError(f"unknown report kind {kind!r} (want {REPORTABLE})")
    if kind == "player" and reporter == target:
        raise ValueError("cannot report yourself")
    text = (reason or "").strip()
    if not text:
        raise ValueError("report needs a reason")
    return {"reporter": reporter, "target": target, "kind": kind, "reason": text}


# --- location-permission handling ------------------------------------------------------------
def can_discover(permission, opt_in):
    """You appear in Nearby only if the browser GRANTED geolocation AND you opted in — this IS the
    per-player `discoverable` bit nearby.py reads. `permission` mirrors the W3C Permissions API state:
    only 'granted' exposes a location; the not-yet-asked 'prompt' and a 'denied' both mean no location,
    so off the map. Fails loud on an unknown permission — a bug/tamper (the browser sends only the three)."""
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown location permission {permission!r} (want {PERMISSIONS})")
    return permission == GRANTED and bool(opt_in)


def check():
    """Fail loud (ValueError) if the public-layer engine regressed. Returns True when clean."""
    bad = []

    # 1. THE 16+ GATE — birthday-aware whole-year age (leap-safe), and the 16 cutoff. `today` is passed
    #    in (no clock in a pure engine). A missing/under-age dob fails the gate; require_age raises.
    today = date(2026, 8, 18)
    if age_years(date(2000, 8, 18), today) != 26:                 # exact birthday today -> ticks over
        bad.append("age_years wrong on an exact birthday")
    if age_years(date(2010, 8, 19), today) != 15:                 # birthday tomorrow -> still 15
        bad.append("age_years counted a birthday that hasn't happened yet")
    if (age_years(date(2008, 2, 29), date(2024, 3, 1)) != 16      # 29-Feb birthday: 16 on 1 Mar 2024,
            or age_years(date(2008, 2, 29), date(2024, 2, 28)) != 15):   # still 15 on 28 Feb 2024
        bad.append("age_years mishandles a 29-Feb (leap-year) birthday")
    if not is_old_enough(date(2010, 8, 18), today):               # exactly 16 today -> in
        bad.append("exactly 16 should clear the gate")
    if is_old_enough(date(2010, 8, 19), today):                   # 15y 364d -> out
        bad.append("under 16 should not clear the gate")
    if is_old_enough(None, today):                                # unknown age fails closed
        bad.append("a missing dob must not clear the gate")
    if require_age(date(2000, 1, 1), today) != 26:                # returns the age when ok
        bad.append("require_age should return the age when old enough")
    for op in (lambda: require_age(date(2011, 8, 18), today),     # 15 -> raise
               lambda: require_age(None, today),                  # unknown -> raise
               lambda: age_years("2000-01-01", today)):           # not a date -> raise
        try:
            op()
            bad.append("age gate accepted an under-age / invalid dob")
        except ValueError:
            pass

    # 2. PRIVACY VIEW POLICY — self always; a block overrides everything; PRIVATE opens only to a
    #    relation; PUBLIC opens to anyone not blocked.
    if not can_view(1, 1, private=True, blocked=True):            # you always see yourself
        bad.append("a user must always see themselves")
    if can_view(1, 2, blocked=True):                              # a block hides even a public account
        bad.append("a block should hide the target")
    if can_view(1, 2, private=True, related=False):               # private + stranger -> hidden
        bad.append("a private account should be hidden from a non-relation")
    if not can_view(1, 2, private=True, related=True):            # private + relation -> visible
        bad.append("a private account should be visible to a relation")
    if not can_view(1, 2):                                        # public + not blocked -> visible
        bad.append("a public account should be visible to anyone not blocked")
    if can_view(1, 2, private=True, related=True, blocked=True):  # block beats a relation
        bad.append("a block should override a relation on a private account")

    # 3. BLOCK — directed store but a SYMMETRIC effect; self/duplicate refused; unblock lifts only the
    #    blocker's own edge; blocked_ids is the exclusion set the other engines take.
    b = block(1, 2, [])
    if b != {"blocker": 1, "blocked": 2}:
        bad.append(f"block built the wrong edge: {b}")
    if not is_blocked(1, 2, [b]) or not is_blocked(2, 1, [b]):    # mutual effect from a one-way block
        bad.append("is_blocked should be true in both directions")
    if is_blocked(1, 3, [b]):
        bad.append("is_blocked should be false for an unrelated pair")
    for op in (lambda: block(1, 1, []),                           # self
               lambda: block(1, 2, [b])):                         # same-direction duplicate
        try:
            op()
            bad.append("block allowed a self/duplicate block")
        except ValueError:
            pass
    two = [b, block(2, 1, [b])]                                   # the reverse edge may coexist
    lifted = unblock(1, 2, two)
    if any(x["blocker"] == 1 and x["blocked"] == 2 for x in lifted):
        bad.append("unblock did not remove the actor's edge")
    if not is_blocked(1, 2, lifted):                              # 2->1 still stands, effect persists
        bad.append("unblock should not lift the other party's block")
    if len(two) != 2:                                             # input untouched (returns a copy)
        bad.append("unblock mutated the input list")
    try:
        unblock(1, 3, [b])                                        # 1 never blocked 3 -> raise
        bad.append("unblock allowed lifting a block that doesn't exist")
    except ValueError:
        pass
    net = [{"blocker": 1, "blocked": 2}, {"blocker": 3, "blocked": 1}, {"blocker": 4, "blocked": 5}]
    if blocked_ids(1, net) != {2, 3}:                             # 1 blocked 2, and 3 blocked 1
        bad.append(f"blocked_ids wrong: {blocked_ids(1, net)}, want {{2, 3}}")

    # 4. REPORT — reason trust guard (non-empty, stripped), a valid surface kind, no self-report of a
    #    player; the reason arrives from a user.
    r = report(1, 2, "  spam and abuse  ", "message")
    if r != {"reporter": 1, "target": 2, "kind": "message", "reason": "spam and abuse"}:
        bad.append(f"report built the wrong record: {r}")
    if report(1, 2, "harassment")["kind"] != "player":           # kind defaults to player
        bad.append("report kind did not default to player")
    for op in (lambda: report(1, 1, "x"),                         # cannot report yourself (player)
               lambda: report(1, 2, "   "),                       # whitespace-only reason
               lambda: report(1, 2, ""),                          # empty reason
               lambda: report(1, 2, "x", "spaceship")):           # unknown kind
        try:
            op()
            bad.append("report accepted an invalid report")
        except ValueError:
            pass

    # 5. LOCATION PERMISSION — discoverable only when GRANTED and opted in; 'prompt'/'denied' or opting
    #    out keep you off the map. This IS nearby's `discoverable` bit. An unknown state raises.
    if not can_discover(GRANTED, True):
        bad.append("granted + opted-in should be discoverable")
    for perm, opt in [(GRANTED, False), (DENIED, True), (PROMPT, True), (DENIED, False)]:
        if can_discover(perm, opt):
            bad.append(f"can_discover({perm!r}, {opt}) should be False")
    try:
        can_discover("allowed", True)                             # not a W3C state -> raise
        bad.append("can_discover accepted an unknown permission")
    except ValueError:
        pass

    if bad:
        raise ValueError("public-layer engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"public OK: 16+ gate, privacy {VISIBILITIES}, block/report, "
          f"location permission {PERMISSIONS} (discoverable = granted + opted-in)")
