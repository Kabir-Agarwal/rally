# Item #9 — Add practice-vs-rated split (SPEC Y3)

Y3 ADD: the **practice-vs-rated split**. Every logged match now carries a **mode**:

- **rated** — a competitive match. It feeds the Elo rating, the rankings and the ranked card
  numbers, exactly the way every match does today.
- **practice** — a casual/friendly hit. It is still logged and kept for the record, but it does
  **not** touch your rating. Practising can't cost you (or win you) rating points.

Rally is LIVE and features land block by block (item #2), so this ships the **split engine** — the
real, testable brain — while the `mode` column on `matches` lands with the batched migrations
(item #19, SPEC Y5 — no session applies schema) and the log-a-game toggle + card wiring land with
the competitions hub (item #10). This is the exact sibling shape of tournaments (item #7) and
leagues (item #8): a pure engine, preflight-gated now, wired to the DB/UI later.

## The one file to know: `practice.py`

A dependency-free, DB-free classification engine over the match dicts `ratings.rebuild` already
consumes. A match is any dict that **may** carry a `"mode"` key — the same optional-key shape
`ratings.py` uses for `"points"`. Everything else about the match stays the rating engine's concern.

- `match["mode"]` → `"rated"` | `"practice"` | absent/`None` (**absent/None == rated**).

Functions:

- `normalize(mode)` — trust-boundary guard. `None`/`""`/absent → `rated`; `"RATED"`/`" Rated "` →
  `rated` (case/space tolerant — it's a UI toggle); anything else **raises** `ValueError` (an
  unknown mode is a bug to surface, never a match silently treated as rated).
- `mode_of(match)` / `is_rated(match)` — the match's canonical mode; whether it feeds the rating.
- `split(matches)` → `(rated, practice)`, each in input order, `rated + practice == all`.
- `for_rating(matches)` — **the one filter that matters**: the rated matches only, in order. A
  caller runs it immediately before `ratings.rebuild(...)`, so practice matches never move a number.

## Why absent == rated (the prod-never-breaks invariant)

Every match already logged has no `mode`. Defaulting absent → `rated` means the split is **purely
additive**: the entire existing history keeps feeding the rating byte-for-byte, and the leaderboard
and cards are unchanged the moment this lands. Nothing has to be back-filled, and prod can't break
on the way in (SPEC Y1). A match only stops counting once it is *explicitly* logged as practice.

## Where it plugs in later (deferred, on purpose)

`db.rating_state` rebuilds from every `status='counted'` match via `db._rating_match_dicts`, and
`app.player_payload` reads the same counted matches for the card. Once the `mode` column exists
(item #19), the join is one line — either `ratings.rebuild(practice.for_rating(dicts))`, or an
`AND COALESCE(mode,'rated')='rated'` in the counted-match query — and the card can show the record
split (`rated` W-L drives the number, `practice` W-L is shown but doesn't). That wiring is item #10's
call when the toggle and schema are there; this item ships the engine it will call. No app/db change
now, so nothing in the live rating path moves yet.

## Enforcement (same mechanism as items #2–#8)

- `deploy.py` `preflight()` calls `practice.check()` beside `tournaments.check()` /
  `leagues.check()` and the Y2 guards. `check()` proves the normalization + trust guard, the
  back-compat default (an un-tagged match is rated), the partition (`split`/`for_rating`), and —
  the whole point — that a **mixed history filtered through `for_rating` rebuilds to the SAME
  ratings as the rated matches alone** (and *differs* from counting both, so the filter isn't a
  no-op), with a lone practice match leaving everyone at baseline. A regression **aborts the
  deploy** before a file is uploaded.
- `test_practice.py` is the runnable check: modes normalize/default, an un-tagged match stays
  rated, `split` partitions in order, practice doesn't move the rating (against the real
  `ratings.rebuild`), and a bad mode fails loud in the pipeline.

## Scope (ponytail)

Built: the split engine (`normalize`/`split`/`for_rating`) + a runnable check, wired into preflight.
**Skipped** (belongs to later blocks): the `mode` column and the counted-match query filter (item
#19 migrations), the log-a-game rated/practice **toggle** and the card's rated-vs-practice record
display (item #10 hub). No new screen (the split is a property of an existing flow, not a tab — so
no `blocks.py` change), no schema, no new dependency, no money.
