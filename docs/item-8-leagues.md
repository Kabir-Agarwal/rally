# Item #8 — Add round-robin leagues (SPEC Y3)

Y3 ADD: **round-robin leagues**, the sibling of tournaments (item #7). Where a tournament is a
single-elimination draw that collapses to one champion, a league is a **round-robin**: every entrant
plays every other exactly once and a **standings table** ranks the field as results arrive. Rally is
LIVE and features land block by block (item #2), so this ships the **round-robin engine** — the real,
testable brain — and lands the leagues **screen as dummy UI** (SPEC Y1). Persisting a league and the
Create/Manage flow arrive with the competitions hub (item #10) and batched migrations (item #19, SPEC
Y5 — no session applies schema), which build on this engine.

## The one file to know: `leagues.py`

A dependency-free, DB-free round-robin engine over plain lists/dicts. It reuses the **match shape** from
`tournaments.py` (`{"a", "b", "winner"}`) so one UI can render both competition types.

- **entrant** — anything hashable (player id / name). Input order is the stable tiebreak order (ranking
  by rating is the caller's job, a later item — the engine takes input order as it).
- **match** — `{"a": entrant, "b": entrant, "winner": entrant|None}`; `winner` `None` = not yet played.
  An **odd** league carries one **BYE** per round (`"b"` — or `"a"` — is `None`): that entrant rests.
- **round** — matches played in parallel (no entrant twice); a **schedule** is a list of rounds.
- **row** — a standings line `{"player", "played", "wins", "losses", "points", "rank"}`.

Functions:

- `schedule(entrants)` — single round-robin by the classic **circle method**: pin one player, rotate the
  rest. Even *n* → *n−1* rounds of *n/2* games, no BYE; odd *n* → *n* rounds, one BYE each. Rejects
  out-of-range (**3..32**), `None`, or duplicate entrants (trust-boundary guard).
- `is_bye(match)` / `round_complete(rnd)` — spot a rest match; true once every **real** match has a winner.
- `standings(entrants, matches)` — the **league table** from any iterable of matches (BYEs and unplayed
  fixtures skipped). 1 point per win; ranked by **points → head-to-head within the tied group → input
  order**, the standard round-robin tiebreak, all computable from winners alone. Rejects a match naming
  a non-entrant or a winner who didn't play in it.
- `play(entrants, decide)` — runs a whole round-robin **LIVE** to a full table via a `decide(a, b)`
  callback; returns `(schedule, table)`. The round-robin analog of `tournaments.play()`.

### Why head-to-head is the tiebreak (and not games/sets)

At this layer the engine only knows **who won each match**, not the score. Head-to-head among the players
level on points is the canonical round-robin rule that's decidable from exactly that. It can still be
circular (A→B→C→A); that group then shares a rank and input order gives a deterministic display order. A
games-or-sets differential needs scores and belongs to a later caller — the same way seeding-by-rating
was deferred for tournaments.

## Enforcement (same mechanism as items #2–#7)

- `deploy.py` `preflight()` calls `leagues.check()` beside `tournaments.check()` and the Y2 guards.
  `check()` builds a 4- and a 5-league, plays one forward to a full table, and asserts the size bounds,
  the **complete** round-robin (every pair once, no repeats), the round structure (odd → one BYE each,
  one BYE per player, nobody double-booked), the live table (top seed sweeps to rank 1, everyone plays
  *n−1*), the **head-to-head** tiebreak, and the table guards. A build that breaks the round-robin math
  **aborts the deploy** before a file is uploaded.
- `test_leagues.py` is the runnable check: complete round-robin, no-BYE even / one-BYE-each odd, live
  standings of a seed-ordered league, head-to-head breaking a tie, a circular tie sharing a rank, and
  empty/bogus results rejected.
- `blocks.py`: `leagues` flipped `off → dummy` — the tab appears with the generic "Coming soon"
  placeholder (SPEC Y1), no app.js changes. `off → dummy → live` completes when item #10 wires the
  create/manage/live-table UI onto this engine.

## Scope (ponytail)

Built: the round-robin engine (schedule + standings + live play) + a runnable check + the dummy-screen
landing. **Skipped** (belongs to later blocks): league persistence and the Create/Manage/live-table UI
(item #10 + migrations item #19), a weighted points system and a games/sets tiebreak (scores are a caller
concern), and double round-robins (single is what Y3 asks for). No schema, no new dependency, no money.
