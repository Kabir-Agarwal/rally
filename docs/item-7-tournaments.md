# Item #7 — Add tournaments: 4–32 draws, BYEs, live brackets (SPEC Y3)

Y3 ADD: **tournaments**. The first Y3 feature-block. Rally is LIVE and features land block by block
(item #2), so this ships the **bracket engine** — the real, testable brain of the feature — and lands
the tournaments **screen as dummy UI** (SPEC Y1). Persisting a tournament and the Create/Manage flow
arrive with the competitions hub (item #10) and batched migrations (item #19, SPEC Y5 — no session
applies schema), which build on this engine.

## The one file to know: `tournaments.py`

A dependency-free, DB-free single-elimination engine over plain lists/dicts:

- **entrant** — anything hashable (player id / name / seed). Input order **is** the seeding: index 0 =
  top seed (seeding *by rating* is the caller's job, a later item).
- **match** — `{"a": entrant|None, "b": entrant|None, "winner": entrant|None}`; a `None` slot is a BYE.
- **round** — a list of matches; a **bracket** is a list of rounds, `round[0]` first.

Functions:

- `bracket_size(n)` — smallest power of two ≥ n; rejects anything outside **4..32** (`5→8`, `20→32`).
- `seed_slots(size)` — seeds `1..size` in classic fold order, so **#1 and #2 can only meet in the
  final**, #1–#4 only in the semis, and so on.
- `first_round(entrants)` — pads the draw to a power of two with **(size − n) BYEs handed to the top
  seeds**, and **auto-advances every BYE**. Rejects `None` / duplicate entrants (trust-boundary guard).
- `next_round(rnd)` — pairs the winners of a **completed** round into the next; refuses an undecided
  round. Rounds past the first never contain a BYE.
- `champion(bracket)` / `play(entrants, decide)` — `play` runs a whole draw **LIVE** to its champion
  using a `decide(a, b)` callback; `champion` reads the winner off the final, `None` until it's decided.

### Why BYEs land on the top seeds for free

Seeds fill the bracket in `seed_slots` order; the highest seed numbers (`n+1..size`) are the BYEs, and
fold seeding always pairs the highest seed numbers against the lowest. A non-full draw has fewer than
half its slots empty (`size < 2n`), so no BYE ever meets another BYE. 6 in a draw → size 8 → 2 BYEs,
to seeds 1 and 2.

## Enforcement (same mechanism as items #2–#6)

- `deploy.py` `preflight()` calls `tournaments.check()` beside `blocks.validate()`, `theme.check()`,
  `chemistry.check()`, `deletion.check()` and `cardstats.check()`. `check()` plays a full 4-draw and a
  6-draw (with BYEs) forward to a single champion and asserts the draw bounds, seeding, BYE placement,
  round-by-round collapse, and the live guards. A build that breaks the bracket math **aborts the
  deploy** before a file is uploaded — the engine stays honest as leagues (#8) and the competitions hub
  (#10) build on it.
- `test_tournaments.py` is the runnable check: bounds round up to a power of two, a full draw has no
  BYEs, BYEs pad to the top seeds, a live draw collapses `[4,2,1]` to one champion, #1/#2 only meet in
  the final, an undecided round can't advance, and `None`/duplicate entrants are rejected.
- `blocks.py`: `tournaments` flipped `off → dummy` — the tab appears with the generic "Coming soon"
  placeholder (SPEC Y1), no app.js changes. `off → dummy → live` completes when item #10 wires the
  create/manage/live-view UI onto this engine.

## Scope (ponytail)

Built: the bracket engine + a runnable check + the dummy-screen landing. **Skipped** (belongs to later
blocks, not this one): tournament persistence and the Create/Manage/live-bracket-render UI (item #10 +
migrations item #19), and seeding-by-rating (the engine takes input order as the seeding). No schema,
no new dependency, no money.
