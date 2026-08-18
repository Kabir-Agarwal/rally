# Item #16 — Add the public layer (SPEC Y3)

Y3 ADD: **public layer — privacy controls, block/report, location-permission handling, 16+ gate.** This
is the item every earlier Y3 block pointed at. `nearby`, `messenger`, `highlights`, `feed` and `orgs`
each built their feature and wrote the *same* deferral into their own docstring — *"block/report, the
16+ gate, who-may-see-whom, location-permission are item #16"*. So #16 is not a new screen; it is the
**consolidation** of the four cross-cutting rules that decide who may **see**, **reach**, **be found by**,
or **take part** at all. The irreducible core is exactly those four decisions, so the engine is exactly
those four — one pure module, `public.py`.

| Part            | What it is                                                                                          |
|-----------------|-----------------------------------------------------------------------------------------------------|
| **16+ gate**    | `age_years(dob, today)` is birthday-aware, whole-year, **leap-safe** (born 29 Feb 2008 → 16 on 1 Mar 2024). `is_old_enough` / `require_age` gate participation at `MIN_AGE = 16`. No clock in a pure engine — the caller passes `today` (a `date`), the same "caller stamps the time" rule `feed`/`messenger` use. Unknown age **fails closed**. |
| **privacy**     | An account is `PUBLIC` or `PRIVATE`. `can_view(viewer, target, private=, blocked=, related=)` is the one screen-level decision: self always; a block overrides everything; a **private** account opens only to a **relation** (an accepted connection / approved follower); a **public** one opens to anyone not blocked. The engine is the *policy*; the caller supplies the *facts* from whichever graph applies — the way `nearby` takes a `blocked` set. |
| **block/report**| `block(actor, other)` is a **directed** edge (like `feed.follow`) but its **effect is symmetric** — `is_blocked` is true either way, so a block hides both directions and cuts messaging both ways. `unblock` lifts only the blocker's own edge. `blocked_ids(me)` is the **exclusion set the other engines already accept** (`nearby(blocked=…)`, a feed filter) — the one-parameter tie-in they each left open. `report(reporter, target, reason, kind)` is a moderation record with a real, non-empty reason. |
| **location perm**| `can_discover(permission, opt_in)` — you appear in **Nearby** only if the browser **GRANTED** geolocation **and** you opted in. `permission` mirrors the **W3C Permissions API** state (`prompt` \| `granted` \| `denied`) — the real browser contract — so `denied` and the not-yet-asked `prompt` both mean *off the map*. This **is** `nearby.py`'s per-player `discoverable` bit. |

## The one file to know: `public.py`

A DB-free, dependency-free engine (stdlib `datetime.date` only), same style as the sibling engines.

- **16+ gate:** `age_years`, `is_old_enough`, `require_age`, `MIN_AGE`.
- **privacy:** `PUBLIC` / `PRIVATE`, `can_view(viewer, target, private=, blocked=, related=)`.
- **block/report:** `block`, `unblock`, `is_blocked`, `blocked_ids`, `report`, `REPORTABLE`.
- **location:** `PROMPT` / `GRANTED` / `DENIED`, `can_discover(permission, opt_in)`.

## Why one policy, not one-per-consumer

`can_view` is used by the profile, the club page (`orgs`' "who-may-see-a-club"), the feed and
**messenger's DM gating** alike — because the rule is the same in every place: *a block forbids it, a
private account only opens to a relation.* Giving each surface its own copy is how the four drift out of
sync. So there is a single `can_view`, and messaging/discovery read the same primitives (`is_blocked`,
`can_discover`). The **age gate is separate on purpose** — it is the *front door* (account-level
eligibility, checked once at onboarding), not a per-pair visibility question, so folding `dob` into every
`can_view` call would be signature bloat for a check already made at the gate.

## The promised tie-in — `blocked_ids`

`nearby` shipped with *"an optional `blocked` set is excluded — one parameter, so item #16 wires
block/report in without a rewrite."* `blocked_ids(me, blocks)` is that parameter: everyone `me` blocked
**and** everyone who blocked `me`. Drop it into `nearby(me, players, blocked=blocked_ids(me, blocks))` or
a feed filter and the block takes effect across the app with **no change to those engines** — the seam
was left open, and this fills it.

## Enforcement (same mechanism as items #2–#15)

- `deploy.py` `preflight()` calls `public.check()` beside `orgs.check()` and the rest. `check()` proves the
  age math (leap-year birthday boundary + the 16 cutoff), the view policy (self / block / private-vs-
  relation / public), the block lifecycle (directed store, symmetric effect, `blocked_ids`, `unblock`,
  purity), the report guards, and the location-permission gate. A regression **aborts the deploy** before
  a file is uploaded.
- `test_public.py` is the runnable check (pytest) — green alongside the full suite (**253 passed**).

## Scope (ponytail)

Built: the 16+ gate + privacy view policy + block/report + location-permission engine, a runnable check,
wired into preflight. **No new nav tab** — the public layer is cross-cutting: the privacy toggle, the
Block/Report buttons, the blocked-users list, the location prompt and the age gate surface *within* the
existing Profile + each feature screen, so nothing in `blocks.py` flips (there is no new screen to stage).
**Skipped** (belongs to later blocks): the columns (`accounts.visibility`, `players.dob`,
`players.location_permission` + `discoverable`) and the tables (`blocks`, `reports`) — item #19 batched
migrations (SPEC Y5, no session applies schema); the actual UI controls; a **moderation review queue /
admin actions** on reports (reports here are *recorded*; acting on them is an ops surface the spec doesn't
name); **per-field** privacy granularity (private/public is the irreducible control). No schema, no new
dependency, no money.

## Related — the free-tier public-traffic cost card

STATUS.md's WAITING-OWNER cost card (item #0, Y7) notes the *free* mitigation — cutting the 3-second Live
poll — is "part of item 16 / Y1 prod-safe". That is a **separate, owner-gated** performance/cost decision
(it changes the polling firehose, not who-may-see-whom) and is left on that card for the owner; this item
delivers the four **policy** rules the spec lists under "public layer". The card still stands.
