# Item #6 — Keep earned-from-0 card stats (SPEC Y2)

Y2 KEEP: **earned-from-0 card stats**. Rally is LIVE and Y3 features land block by block (item #2);
tournaments, leagues and the practice-vs-rated split all feed the player card, and Y4 puts an
Elo-style skill rating on it. "Keep earned-from-0 card stats" makes the card a **contract**, not a
promise, so a later block can't put a number on the card that wasn't earned on court.

## What "earned-from-0 card stats" is

The player card is `app.player_payload(con, gid, pid)`. Every field on it is **earned by playing,
starting from zero** — nothing is seeded, assigned, or self-rated:

- **From 0.** A brand-new player has an empty record — `wins=0`, `losses=0`, `last5=[]`,
  `singles_n=0`, `doubles_n=0`, no `pairs` — and both ratings sit exactly at the shared
  `ratings.START` baseline, both `*_prov` (provisional). This is the same rule as Y2's **SKIP
  self-rating slider onboarding**, seen from the other end: you don't onboard with a number, you
  start at zero and earn it.
- **Earned.** Each `status='counted'` match moves the card — a `W`/`L` on the record and the form
  strip, `+1` on the match count, and the rating off baseline (winner up, loser down).
- **Counted play only.** `wins`/`losses`/`last5`/`*_n` are derived **solely** from `status='counted'`
  matches. A pending (unapproved) match — not yet earned — puts nothing on the card.
- **Form window.** `last5` is the last five results only (recent-first), capped at 5 however many
  matches have been played.
- **Provisional until proven.** A rating reads provisional until `ratings.MIN_MATCHES` (5) counted
  matches are earned — a thin, barely-earned rating never poses as ranked.

## The one file to know: `cardstats.py`

`cardstats.check()` drives the **real** `app.player_payload` over the real `logic` + `db` + `ratings`
engine on an in-memory DB (create players, play counted singles, read the card back) and fails loud if
the contract regressed:

1. **From zero** — a brand-new player's card is all-zero and un-seeded: empty record, rating at
   `round(ratings.START)`, both modes provisional.
2. **Earned** — one counted win gives the winner `1W 0L ['W'] n=1` with a rating above baseline, and
   the loser `0W 1L ['L'] n=1` below it.
3. **Counted play only** — a pending (unapproved) match leaves the card empty (`0W 0L [] n=0`).
4. **Form window** — after 6 earned wins, `wins=6` but `last5 == ['W']*5` (capped at the last five).
5. **Provisional gate** — provisional below `MIN_MATCHES` earned matches, ranked at exactly
   `MIN_MATCHES`, with the gate frozen at `RANKED_GATE = 5` (a block moving `ratings.MIN_MATCHES`
   without moving this — or vice-versa — trips the frozen-constant check).

## Enforcement (same mechanism as items #2–#5)

- `deploy.py` `preflight()` calls `cardstats.check()` right beside `blocks.validate()`,
  `theme.check()`, `chemistry.check()` and `deletion.check()`. A build that seeds the card or
  mis-counts what's earned **aborts the deploy** before any file is uploaded.
- `test_cardstats.py` is the runnable check: the live payload satisfies the contract, and the two
  regressions that matter — a block that moves the ranked gate, or one that breaks approval so
  matches never count and nothing gets earned — are caught.

Scope: the guard locks the card contract — `app.player_payload` + the `status='counted'` predicate +
`ratings.START`/`MIN_MATCHES` are the single source of truth for the card's numbers. The existing
behaviour tests (`test_ranks_list.py`, `test_ui_support.py`, `test_tennis.py`) still cover the routes
and the leaderboard; this freezes the earned-from-0 contract they assume.
