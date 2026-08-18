# Item #13 — Add highlights (SPEC Y3)

Y3 ADD: **highlights (landscape video upload, reputation stars, laurels)**. The item-0 study mapped
this to feature #8, *"content/highlights sharing with reputation"*. One clip, three pure halves:

| Half                  | What it is                                                                        |
|-----------------------|-----------------------------------------------------------------------------------|
| **landscape upload**  | The gate a video clears to become a highlight. A highlight is **landscape** (the spec word) — filmed wide, not a portrait phone clip — so it plays full-bleed and lines up with the Y6 tool's landscape court framing. `accept_upload()` is the **trust boundary** (the file arrives from a user) and refuses portrait/square, an unknown format, an oversized file or an over-long clip, **each with the reason to show**. |
| **reputation stars**  | Viewers rate a highlight **1–5 stars**; its reputation is the **average + vote count**. `rate()` builds one vote — the DB's unique `(highlight, viewer)` key makes it **one vote per viewer** (an upsert, the friendships-pair shape) — and refuses rating your **own** clip. `reputation()` aggregates. |
| **laurels**           | The earned award a clip wins from its reputation — film-festival wreaths, **none → bronze → silver → gold**. A **votes floor** gates each tier so one 5★ vote can't mint gold: the laurel is **earned and credible**, the same *earned-from-0* principle the rest of Rally holds to. `laurel()` maps a reputation to its tier; `card()` joins stars+laurel — the one call the screen makes per clip. |

Rally is LIVE and features land block by block (item #2), so this ships the **engine** — the real,
testable brain — while the `highlights` + `ratings` tables, the upload form, the video player, the
star bar and the laurel badge land with the batched migrations (item #19, SPEC Y5 — no session applies
schema). Same sibling shape as items #7–#12: a pure engine, preflight-gated now, wired to the DB/UI
later. The Highlights screen lands as **dummy UI** now (`blocks.py`: highlights `off -> dummy`), so the
**Highlights** tab and `/highlights` route go live as a "Coming soon" placeholder with the engine
proven behind them.

## The one file to know: `highlights.py`

A DB-free engine over plain dicts (same style as the sibling engines).

- `accept_upload(video)` — `video = {"width","height","duration_s","size_bytes","format", …}`. Returns
  it normalised (adds `"aspect"`, extra keys pass through) or **raises `ValueError` with the reason**.
  Headline rule first: **landscape** — `width` must exceed `height`, so **portrait and square are
  out**. Then an allowed container (`mp4`/`mov`/`webm`, case- and dot-tolerant), `≤ MAX_SIZE_MB`,
  `≤ MAX_DURATION_S`.
- `rate(highlight, viewer, stars, owner)` — build one star vote (caller persists; the unique
  `(highlight, viewer)` key is the upsert). **Trust guards**: you cannot rate your **own** highlight,
  and `stars` is a **whole 1–5** (bool and floats rejected).
- `reputation(ratings, highlight)` — `{"stars": average (1dp), "votes": n}`; only this clip's votes,
  and an unrated clip is `{"stars": 0.0, "votes": 0}` (not an error).
- `laurel(rep)` — `'none' | 'bronze' | 'silver' | 'gold'`: the highest tier whose **average-stars AND
  votes floor** are both met. Thresholds: gold ≥4.5 & ≥10 votes, silver ≥4.0 & ≥5, bronze ≥3.5 & ≥3.
- `card(ratings, highlight)` — the one call the screen makes per clip: `reputation` joined with the
  `laurel` it earned (`{"stars","votes","laurel"}`), the way `nearby.discover()` joins its halves.

## Why the star gate has a votes floor

A laurel earned from a single rave vote would mean nothing — the same reason Rally's card stats are
*earned from 0* and UTR-style ratings carry a credibility signal (item-0 study, features #7/#8). The
floor (`LAUREL_TIERS`) is that credibility: a high average earns its wreath only once enough people
have voted.

## Why the gate is metadata-only (not pixel decoding)

`accept_upload` reads the dimensions/format/size/duration the caller lifts off the file — it does not
decode the video to confirm orientation. Decoding pixels is the **Y6 laptop-only vision tool's** job
(rally segmentation / highlight reel / heatmaps, items #20–21, owner ruling: LAST). This engine is the
upload/reputation layer those finished clips land in, marked with a `ponytail:` comment at the ceiling.

## Enforcement (same mechanism as items #2–#12)

- `deploy.py` `preflight()` calls `highlights.check()` beside `messenger.check()` / `nearby.check()`
  and the rest. `check()` proves the landscape gate (accept + every rejection reason), the star trust
  guards, the reputation average, and the laurel tiers incl. the votes floor + the joined `card()`. A
  regression **aborts the deploy** before a file is uploaded.
- `test_highlights.py` is the runnable check (pytest): the upload gate, the vote guards, reputation,
  the laurel table and `card()` — green alongside the full suite.

## Scope (ponytail)

Built: the landscape-upload + reputation-stars + laurels engine + a runnable check, wired into
preflight, plus the dummy **Highlights** tab. **Skipped** (belongs to later blocks): the highlights/
ratings tables + the upload form / player / star bar / laurel badge (item #19 migrations); block/report
+ 16+ gate (item #16 public layer); the actual video **processing** — rally segmentation, highlight
reel, heatmaps (Y6 laptop-only tool, items #20–21). No schema, no new dependency, no money.
