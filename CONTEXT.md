# CONTEXT.md — Rally (tennis scorer)

## THE BIG ONE — functions moved to bom1, next to the DB (2026-07-28, latest)
**`vercel.json` now pins `"regions": ["bom1"]`. Every endpoint got 3-7x faster. This single line
was worth more than every query optimisation in this file combined.**

Root cause, verified rather than assumed: the Vercel functions ran in **iad1 (Virginia)** while
the Supabase project `rally` lives in **ap-south-1 (Mumbai)** — confirmed via the Supabase API,
which reports `"region": "ap-south-1"`. Every DB round trip crossed ~12,000km. That is the whole
explanation for the "~0.25s per round trip + ~0.53s floor" cost model recorded below: the floor
was the India-client -> iad1 hop, and each query added a Virginia<->Mumbai return trip.

`bom1` is Vercel's Mumbai region, so the function now sits in the same city as the database.

### Before/after — LIVE production, perf_probe medians of 6, cold call discarded
| endpoint | BEFORE (iad1), 2 runs | AFTER (bom1), 3 runs | speed-up |
|---|---|---|---|
| `/api/leaderboard` | 1.324s / 1.291s → **~1.31s** | 0.255s / 0.176s / 0.184s → **~0.18s** | **~7x** |
| `/api/live` | 0.531s / 0.532s → **~0.53s** | 0.165s / 0.166s / 0.160s → **~0.17s** | **~3x** |
| `/api/me` | 0.561s / 0.530s → **~0.55s** | 0.164s / 0.165s / 0.155s → **~0.16s** | **~3.4x** |
| `/api/auth/config` (no DB) | 0.342s / 0.355s → **~0.35s** | 0.173s / 0.144s / 0.162s → **~0.16s** | **~2.2x** |

(The one outlier, 0.255s, was a cold start; the two warm runs agree at 0.176/0.184s.)

**The per-round-trip cost collapsed from ~250ms to ~10ms.** Measured the same way as before:
`/api/leaderboard` makes 2 DB round trips and `/api/live` makes 0, and they now differ by just
0.019s — about **10ms per round trip, down from ~250ms. A 25x drop.**

### What this means for the earlier work (worth being honest about)
The two query fixes below are still correct, but their *absolute* value just shrank by ~25x,
because a round trip is no longer expensive. The honest ranking of this session's leaderboard
work: **region move (1.31s → 0.18s) >> removing one round trip (1.505s → 1.31s) > the N+1 fix
(~0s today).** The N+1 fix still earns its place — it is O(1) instead of O(matches), so it stops
the endpoint degrading as real data arrives — but the round-trip *count* is no longer the thing to
design around. **The new rule for this stack: keep functions in the same region as the database;
after that, query count is a second-order concern.**

Verified after the move: deployment `dpl_FueZUEYPY3YVDFtwdcqPzUKDtrPN` reports
`"regions": ["bom1"]` (was `["iad1"]`), and at runtime `x-vercel-id` is now `bom1::bom1::…`
(was `bom1::iad1::…`) — edge and compute both in Mumbai. Page loads anonymously, renders the
sign-in screen, zero console errors; `/api/leaderboard` payload byte-for-byte equivalent
(2 players, 0 counted matches, `scope: everyone`).

Not used: `functionFailoverRegions` (Enterprise-only). A single default region via the documented
top-level `regions` key works on this plan — the deploy is the proof.

## /api/leaderboard — 1.505s -> 1.30s, and the real cost model (2026-07-28, earlier)
Two separate fixes. **Only the second one moved the live number**, and the reason why is the
important part.

**1. The N+1 in `rating_state()` (`f3fb88a`) — real, proven, but worth 0s today.**
`rating_state()` replayed every counted match and called `_match_to_dict()` per match, firing 3
queries each (`match_players`, `match_sets`, `point_logs`): `1 + 3*(counted matches)` sequential
round trips. Now each child table is read in ONE query joined to the same `status='counted'`
predicate, grouped in Python; row order preserved by reusing the old ORDER BYs. New test
`test_leaderboard_query_count_does_not_grow_with_matches` measures it: adding 12 counted matches
took the endpoint **11 -> 47** round trips before, and leaves it **flat at 9** now.
**It changed live latency by ~35ms, because production currently holds 2 players and ZERO counted
matches** — N was 0, so there was no N+1 to pay. It is insurance, not today's win: at ~0.2-0.3s
per round trip, the old code would have added ~0.6-0.9s **per counted match** as real data lands.
`test_query_budget` only guarded the PLAYERS axis, which is why this sat unnoticed; the matches
axis is now guarded too.

**2. The actual win — one less round trip (`3ad591c`): 1.505s -> 1.30s.**
`live_player_ids()` was a whole round trip just to build a set of ids, so it is now an `EXISTS`
folded into the board's player query. (`live_player_ids()` stays for its other callers.) Added
`test_live_flag_marks_only_players_in_a_live_match` — nothing covered that flag before.

### The cost model (measured, and the thing to reason with from now on)
Anonymous `/api/live` makes **ZERO** DB queries and still takes **0.53s**. Anonymous
`/api/leaderboard` made **3** and took 1.47s. So:
* **~0.53s is a fixed floor** — cold-ish function + connection + framework, before any query.
* **~0.2-0.3s is the cost of EACH sequential Postgres round trip**, essentially regardless of what
  the query does (production has 2 players; these queries are trivial).
Therefore on this stack **the only lever that matters is the NUMBER of sequential round trips.**
Optimising a query body buys nothing; removing a trip buys ~0.25s. `/api/leaderboard` is now 2
trips (counted matches + players); the floor for it is ~0.53s + 2 trips ≈ 1.0-1.1s. Getting below
that means merging those two unrelated queries (ugly) or cutting per-trip latency (infra: the
Vercel function is `iad1`, so a distant/pooled Supabase region is the suspect — not a code fix).

### Before/after on LIVE production (perf_probe medians of 6, cold call discarded)
| run | `/api/leaderboard` | note |
|---|---|---|
| before, 3 runs | 1.497s / 1.505s / **1.510s** | pre-fix baseline, stable |
| after N+1 fix only | 1.471s / 1.467s | ~35ms — N was 0, as explained above |
| after both fixes | **1.299s / 1.305s** | ~205ms saved by removing one trip |

**1.505s -> ~1.30s, now inside the ~1.05-1.45s projection** (it was above it). `/api/live`
unchanged at ~0.54s, `/api/me` ~0.53s, `/api/auth/config` ~0.35s. Live payload verified identical
(2 players, same fields, `scope: everyone`) and the page still loads anonymously with zero console
errors. 118 pytest + all three Node suites green.

## DEPLOYING (read this first) — automatic on push to `master`
**Git integration is live and verified (2026-07-28).** Vercel project `rally-scorer` is connected
to `Kabir-Agarwal/rally`, production branch `master`. **To ship: push to `master`.** A production
deployment is created within ~6s and is READY in ~20-25s.

**`deploy.py` is LEGACY — do not use it.** It file-uploads a tree with a token and predates the
git connection; it is kept only for reference. Nothing needs `VERCEL_TOKEN` any more, which is
what blocked the two dispatches below.

First auto-deploy verified end to end: commit `8000bce` → `dpl_8ryLUf7FmPgQqmhqw6k4ugiGEVLR`,
`source: git`, `target: production`, READY (built 1785237917547 → ready 1785237938785, ~21s),
aliased to rally-scorer.vercel.app. Live: HTTP 200 anonymously, renders the sign-in screen
(Google/email, no guest Continue), **zero console messages/errors**. Served asset hash
`c2da2ef4a3` — exactly the md5 of the static files at `8000bce` **as stored in git**, vs
`22149a6e09` for old prod `6acc531`. So the merged work (`4717afa`) is finally LIVE.

> Gotcha for anyone recomputing `ASSET_V` on Windows: `core.autocrlf=true` means the working tree
> has CRLF while git (and therefore Vercel's Linux build) has LF, so hashing the working tree
> gives a different value (`84dfd779e1`) than production serves. Hash the git blobs, not the
> checkout.

### AFTER numbers (production, post-deploy, medians of 6, two independent runs)
| endpoint | before (old bundle) | after run 1 | after run 2 | projection | verdict |
|---|---|---|---|---|---|
| `/api/live` | 1.110s | **0.627s** | **0.536s** | ~0.85-0.95s | **beat it** |
| `/api/leaderboard` | 1.508s | **1.497s** | **1.505s** | ~1.05-1.45s | **missed — no change** |

`/api/live` came in well under projection. **`/api/leaderboard` did not improve at all** (1.508s →
~1.50s) and sits above the projected range; both runs agree to within 8ms, so this is not noise.
The leaderboard path still needs work — the boot/auth wins did not touch it.

NOT MEASURED: two consecutive authenticated `/api/me` calls (the direct test of the verification
cache). It needs a REAL signed-in Supabase session token; a bogus token is never cached, and
signing in requires credentials. Closest available proxy is the probe's `delta` column — one
verification round trip costs ~0.24-0.64s, which is what the cache avoids on repeat calls.

## 2026-07-28 auto-deploy trigger — first attempt, git connection was not yet active (superseded)
Tested the claim that `rally-scorer` is now git-connected (production branch `master`). It is
not. Pushed empty commit `cb6a09e` ("trigger: first auto-deploy via git integration") at
10:42:08Z; polled the Vercel API for 5 min (deadline 10:47:08Z) and past it. **Zero** production
deployments created since `dpl_1AJQ8EkguHXcuLtGqGjgWeYZb5sV` — that is still `latestDeployment`,
unchanged. Corroborating signals, all negative: repo has no webhooks, no GitHub Deployments, and
no commit statuses/check-runs on `cb6a09e` (state `pending`, 0 total); and the Vercel project's
own `updatedAt` (1785172356019) is ~17.5h OLDER than the push, i.e. the project config was never
modified to add a git link.

**So: deploys are NOT automatic on push. `deploy.py` is NOT legacy — it is still the only way to
ship, and it still needs a `VERCEL_TOKEN` that is not in this environment** (see the entry
below). Nothing about the deploy story has changed; the merged code (`4717afa`) is still not
live. To actually enable auto-deploy: connect the repo under Vercel → project Settings → Git.

## 2026-07-28-DEPLOY-FROM-LAPTOP dispatch — still BLOCKED, no token on this machine either (earlier)
Ran from the laptop checkout. Task 1 done: local `master` was 3 behind; `git pull --ff-only` →
HEAD `87f511f` (code `4717afa`), matching the dispatch exactly. **Task 2 STOPPED — no
`VERCEL_TOKEN` here either.** The dispatch said it was in this repo's `.env`; it is not — `.env`
contains only `ADMIN_KEY`. Also checked: shell env, `~/.vercel`, `~/.config`/`~/.local` and
`%APPDATA%` Vercel CLI dirs, every `.env*` under `Desktop`/`projects`, and `git log -S` over all
75 commits. The only two hits for the string `VERCEL_TOKEN` in the repo are `deploy.py` (which
reads it from the environment only) and this file. No workaround attempted, per instruction.

Tasks 3–4 therefore report BEFORE numbers, not after. Vercel API confirms newest production is
still `dpl_1AJQ8EkguHXcuLtGqGjgWeYZb5sV` — no newer deployment exists, so the merged code is NOT
live. `perf_probe.py` against production (medians, old bundle): `/api/live` **1.110s** vs the
~0.85–0.95s projection, `/api/leaderboard` **1.508s** vs the ~1.05–1.45s projection — both above
the projected range, as expected for un-deployed code, and consistent with the recorded baseline
below (1.03–1.09s / 1.41s), which re-confirms production is unchanged. To finish:
`VERCEL_TOKEN=... python deploy.py`, then re-run Tasks 3–4 for real after-numbers.

## 2026-07-28-MERGE-AND-DEPLOY dispatch — merged & tested, deploy BLOCKED (earlier)
Task 1 done: PR #1 (`claude/rally-boot-header-ranks-d9n93p`, base `6acc531`, clean/no conflicts
per `mergeable_state` and a `git merge-tree` dry run) fast-forwarded into `master` and pushed —
master is now `4717afa`, +1163/-83 as expected. Task 2 done: full suite green on merged master —
116 pytest, and all three Node suites (`test_boot.cjs` 18 checks, `test_engine.cjs`,
`test_sync.cjs`) OK. **Task 3 STOPPED — no `VERCEL_TOKEN` in this environment either** (checked
env, `~/.vercel`, git config, `.env` — none exist; confirmed via the Vercel API that production
is still `dpl_1AJQ8EkguHXcuLtGqGjgWeYZb5sV`, i.e. master `6acc531`, unchanged from before this
merge). Per instruction, no workaround was attempted (the Vercel MCP `deploy_to_vercel` path
requires the whole file tree inline and was already ruled out as impractical in the prior
dispatch). **Tasks 4 (live verify) and 5 (perf_probe after-numbers) could not run** — there is no
new deployment to verify or measure; running `perf_probe.py` against current production would
only reproduce the existing pre-merge baseline below, not an "after" number for this merge. To
finish this dispatch: `VERCEL_TOKEN=... python deploy.py`, then re-run Tasks 4 and 5.

## Boot speed + header + Ranks (2026-07-28) — built & tested, **NOT DEPLOYED** (earlier)
Branch `claude/rally-boot-header-ranks-d9n93p`, on top of master `6acc531` (verified: nothing had
landed after it). 116 Python + 18 Node boot checks green. Browser-verified with Playwright,
including an A/B against master. **Deploy is blocked:** no `VERCEL_TOKEN` in this environment —
see "Deploy — BLOCKED" below. Nothing in this section is live yet.

- **Task 1 — boot resilience (the "Rally couldn't start" on first load).** REAL cause found:
  `startBoot()` armed a blind `setTimeout(failOpen, 4500)` wall-clock backstop that fired even
  while boot was progressing normally, and every boot fetch was a ONE-SHOT 4–6s race. A Vercel
  cold start (~1.5s before any of our code runs) + mobile RTT + the then-per-request token
  verification lost that race on a phone's first load; a reload won because the function was warm.
  The same 4.5s deadline also made the earlier `Auth.config()` retry fix (3 × 10s = up to 32s)
  *unreachable* — it could never finish before `failOpen` fired.
  - `resilient(make, opts)` + a single `NET` budget (3 attempts × 12s, backoff). `make` is a
    FUNCTION so each attempt issues a NEW request — re-awaiting one stalled promise can't recover.
    `FAILED` is a distinct sentinel, so "server said null" ≠ "couldn't reach the server".
  - The backstop is now a PROGRESS watchdog (`BOOT` config): it gives up only after `stallMs`
    (25s) with no milestone or `maxMs` (75s) total. Slow gets an honest "Starting Rally… slow
    connection" note; the failure card is reserved for a boot that throws or genuinely stalls.
  - **Audited the whole boot path for the same "slow == broken" class** (the sign-in mock-fallback
    bug was this class) and fixed every instance:
    * `ensureIdentity()` fabricated `{signed_in:false}` after 4s — a signed-in user then read as
      signed OUT (no "you" card, `/?join=` codes dropped). Now retries; if the server is truly
      unreachable it leaves `ME` untouched instead of inventing an answer, and never forces the
      "Set up your player" gate off a guess.
    * `staleTokenGuard()`/`_fetchMe()` and `Auth.refreshSession()` retry; only a DEFINITIVE
      `signed_in:false` from a real reply may sign anyone out.
    * `initLive`/`loadRanks`/`loadHistory`/`loadEditor`: patient on first load; a dropped *poll*
      refresh now KEEPS the data on screen instead of replacing it with an error.
    * `log.js refreshMeta()` was unbounded AND awaited first in `initLog`, so a stalled
      `/api/meta` could stop the Log tab rendering at all. Bounded, retried, non-fatal.
    * Sign-in card shows "Connecting…" → "slow connection, still trying" instead of a bare "…".
  - A/B **measured** (Playwright, latency injected on every `/api/`): at 5s/request master shows
    "Rally couldn't start" at 4689ms; this branch renders real content at 10122ms. With 3 API
    calls failing then recovering, master lands on "Couldn't load live matches"; this branch
    renders real content at 2888ms. At 2s/request both work — master by ~400ms, which is why the
    bug looked intermittent on fast wifi and constant on a phone.

- **Task 2 — per-request latency. MEASURED, not guessed** (production, warm, near-empty DB;
  medians of 6, `perf_probe.py` reproduces it). Baseline: `/static/style.css` 0.24s ·
  `/api/auth/config` (python, no DB, no auth) 0.24s · `/api/me` 0.42s · `/api/live` 1.03–1.09s ·
  `/api/leaderboard` 1.41s. Adding a bearer token to `/api/me`: 0.42s → **1.01s**.
  So the fixed overhead was two things, and neither was slow SQL:
  - **~0.6s per authenticated request: `auth._verify_supabase()` called
    `{SUPABASE_URL}/auth/v1/user` on EVERY request** (blocking `urllib`), including every 3s Live
    poll. Now cached per process for `AUTH_VERIFY_TTL` (default 60s, env-tunable; `0` disables).
    End-to-end demo against a stub Supabase at the measured 0.6s: 6 authenticated requests =
    **1** verification (0.608s then 0.002s ×5) vs **6** × 0.605s with the cache off.
    **Auth is NOT weakened** — pinned by 9 tests in `test_authcache.py`:
    only Supabase-CONFIRMED tokens are cached; rejections are NEVER cached and evict any earlier
    confirmation; the token's own `exp` is enforced on every cache hit, so an expired token fails
    mid-TTL; a token with no readable `exp` is never cached; the cache is bounded (512) and
    per-instance. The one real, bounded cost: a token revoked server-side keeps working for **at
    most 60s** after its last confirmation. (Local JWT verification would be faster still but
    would never detect revocation at all, and we don't hold the JWT secret.)
  - **Sequential Postgres round trips.** `leaderboard_rows()` called `friendship()` once per
    listed player — on the UNFILTERED board that is one round trip per player in the whole app.
    Replaced by one `db.friend_map()` query: **10 → 5** round trips, now constant in player count
    (`test_query_budget.py` adds 40 players and asserts the count doesn't move). `/api/live`:
    **4 → 3** — it no longer rebuilds every rating when nothing is live (that scan only feeds
    `win_prob`, so it was pure waste on the common empty poll).
  - Deliberately NOT changed: `pool_pre_ping=True` costs a round trip per request but guards
    against stale pooled connections in a serverless + Supabase-pooler setup; correctness wins.
    `rating_state()`/`match_view()` still do per-match queries — invisible at today's data volume
    (0 counted matches) and therefore NOT what the measurement pointed at, but they are the next
    cliff as matches accumulate.

- **Task 3 — header.** Game name (bold) + real name underneath, **top-left**, tappable → one
  sheet editing BOTH via the existing `/api/me/rename`; the group filter chip moved **top-right**
  (still opens the existing switcher). Both sides ellipsis, so a long name can't push the chip
  off screen. The old header's "code X · public/private" subtitle is gone — that lives on the
  group cards in Groups and on the switcher rows.

- **Task 4 — Ranks is ONE list.** Server ships `rows` in display order (ranked first, then
  under-5); `ranked`/`provisional` remain as views so nothing reading them breaks. Under-5
  players are greyed rows INLINE (`.lbrow.prov`, opacity .55) with "N of 5" where the rank number
  would be, plus "unranked until 5 matches". The separate "Minimum 5 matches" section is deleted.
  Still fully tappable (verified: a greyed row opens the player sheet).

- **Bug I introduced and fixed during Task 1:** the slow-connection note wrote `innerHTML` into
  `#tabContent`, which holds the tab PANELS — that detached the rendered panel while `PANELS`
  kept the orphan, so `renderTab` wouldn't rebuild it and the app went BLANK on a slow
  connection. Caught by the 5s-latency browser test, not by unit tests. It is now appended as its
  own node; regression test added (`test_boot.cjs` #16b).
- Also: `.psheet` action buttons no longer sit on top of the fixed tab bar (pre-existing; the new
  name editor inherited it).

- **New tests:** `test_authcache.py` (9, auth-cache security), `test_query_budget.py` (4, DB
  round-trip budget + N+1 regression), `test_ranks_list.py` (3, one-list payload), and
  `test_boot.cjs` grew to 18 checks (retry recovery, progress-aware watchdog, the shipped budget
  itself, slow-note non-destructiveness). `test_boot.cjs` runs in ~3s: `static/app.js` exposes
  `window.NET`/`window.BOOT` so tests can shrink the budget, and `window.RALLY_NO_AUTOBOOT` stops
  app.js's own `setTimeout(startBoot, 0)` from racing the tests.

- **Deploy — BLOCKED (not done).** `deploy.py` needs `VERCEL_TOKEN`; it is not in this
  environment (checked env, `~/.vercel`, git config, repo). The Vercel MCP *is* authenticated and
  can see project `rally-scorer` (`prj_OoilZUL1M8PaKeJhpJ5Ue8ZTxUlH`, team
  `team_0zE1g36I2GS0ssWZe00gnSkK`), but its `deploy_to_vercel` requires the whole file tree inline
  in one call (~444KB base64 for the runtime set), which is not practical. **To ship:**
  `VERCEL_TOKEN=... python deploy.py`. Current production is still `dpl_1AJQ8EkguHXcuLtGqGjgWeYZb5sV`
  (master `6acc531`), which is a rollback candidate. After deploying, run
  `python perf_probe.py` and compare against the baseline numbers above — and read the caveat in
  that file's docstring: it measures the COST of one verification (rejections are never cached),
  not the improvement; for the improvement, time two consecutive `/api/me` calls with a real
  signed-in token.

- **NOT verified by me (needs his phones / a deploy):** anything on real hardware or through real
  Supabase OAuth — the actual first-load-on-a-phone fix, real Google sign-in, `navigator.share`,
  and the production latency after-numbers. All boot latency evidence here comes from injected
  latency in headless Chromium against a local server, and all auth-cache evidence from a stub
  Supabase; the live per-request numbers above are real measurements of the CURRENT production.

## Ranks add-friend + group join-link + create-dup fix (2026-07-27) — deployed
100 Python + 3 Node green. Browser-verified in mock mode (one session, seeded players).
- **Task 1 — group-create "duplicate" (REAL cause).** NOT an optimistic double-insert. `createGroup`
  wrote a persistent "✔ created / share this code" card into `#justCreated` AND `renderGroupRows`
  rendered the same group into `#groupRows` right below it — two cards for one group, stacked. Fix:
  deleted the `#justCreated` card entirely (the group now shows once in Your Groups, with its own
  Copy/Share); a brief `toast()` confirms. `renderGroupRows` uses `replaceChildren`, so it never
  double-appends. **Double tap COULD previously create two real groups** (no in-flight guard → two
  POST /api/group/create). Fixed: Create button disables + guards while the request is in flight.
  Verified: creating a group yields exactly ONE card; two simultaneous createGroup() calls made ONE
  group.
- **Task 2 — share a group by link.** Each group card got Copy + Share next to the code (mirrors the
  YOU-card friend link). Link = origin + "/?join=<GROUP CODE>". Share = navigator.share, clipboard
  fallback. `/?join=CODE` on boot: `storePendingJoin()` persists the code to localStorage BEFORE any
  sign-in redirect (so it survives OAuth), `completePendingJoin()` runs once a signed-in player
  exists. Verified all four: public→"Joined <name>" + FILTER set + lands on /g/CODE/live; private→
  "Requested… waiting for the admin"; unknown→"no group with that code" (not silent); signed-out→code
  persisted through, completed after sign-in. Joining a group does NOT create a friendship (verified:
  fresh player stays rel=none after join).
- **Task 3 — add a friend from the leaderboard.** Server: `/api/leaderboard` rows now carry `code`
  and `rel` (you/friend/sent/incoming/none) via `_relationship`. Tapping a Ranks row opens a bottom
  sheet (`.psheet`, reuses card/btn styles): Name#CODE, rating · N matches, "See stats" (= old tap),
  and an Add-friend control whose state = reality — own row: none; friend: "Already a friend"; sent:
  "Friend request sent"; else (none/incoming): active "Add friend" → POST /api/friend/request (an
  incoming request auto-accepts). Each row's subtitle now shows the relationship in plain words
  (you/friend/requested/not a friend). All four states + both Add actions verified in-browser; test
  `test_leaderboard_carries_code_and_relationship`.
- **UNVERIFIED BY ME (needs his two phones):** real Google sign-in, the mobile navigator.share
  Copy/Share sheet, and the signed-OUT→sign-in→auto-join round trip through actual Supabase OAuth
  (the query-drop that `storePendingJoin` guards against only happens on a real OAuth redirect). All
  logic exercised here with mock guest tokens + direct completePendingJoin/deep-link calls.

## State
Working, tested, verified end-to-end. Built locally, **not deployed**.
Product name is **Rally**, subtitle **"tennis scorer"** (header, titles, README, Docker labels).
No personal names anywhere in UI/README/comments/seeds (seeds are generic: Ann/Bob/Cara/Dan).
38 pytest tests green (25 base + 9 admin + 4 backend).

- `ratings.py` — pure rating engine (singles/doubles/pairs/TT). `python ratings.py` → OK.
- `db.py` — SQLite schema + helpers + per-group rating rebuild. `python db.py` → OK.
- `logic.py` — match lifecycle + approval/delete state machine. `python logic.py` → OK.
- `scoring.py` — serving order, point→sets reconstruction, serve/return + story stats. `python scoring.py` → OK.
- `app.py` — FastAPI: tab pages, JSON polling API, write endpoints.
- `templates/` (Jinja2) + `static/style.css` (clay theme) + `static/app.js` (all client logic).
- `test_tennis.py` + `test_app.py` — 25 pytest tests, all green.

## Run
```
uvicorn app:app --port 7860      # http://127.0.0.1:7860
pytest -q                        # 25 tests
docker build -t tennis-scores . && docker run -p 7860:7860 tennis-scores
```
SQLite file `tennis.db` is created on first run (gitignored).

## Group & permission model
- No accounts. A group = a private space keyed by one unique 6-char code (A–Z, 2–9).
- **Possessing the code (it is in the URL `/g/<code>/…`) = member = can read + write everything.**
- `is_public` toggle (any member flips it): public → group's players appear on the global
  leaderboard and its live matches show in other groups' "watch only" feed; private →
  excluded from all global feeds.
- Device state (joined groups, "which player am I") lives in `localStorage` only.
- Ratings/records are per group; the same human in two groups = two player rows.

## Rating rules (authoritative summary)
- ELO, start 1200, K=32. `P(A)=1/(1+10^((Rb−Ra)/400))`.
- Margin: `share`=winner's games fraction, `M=clamp(0.75+3·(share−0.5),0.75,1.5)`, `K_eff=K·M`; draw `M=1`.
- Winner: sets → total games → draw (0.5). 0-0 sets ignored. 1–5 sets. Applied in finish order.
- **Singles:** per-player. **Doubles:** team rating = average, one delta, **each partner moves the full delta**.
- **Pair ratings:** each duo its own ELO (1200/K=32), moved only by that duo as a unit, provisional < 3.
- **Win prob:** pair ratings when both duos have 3+ pair matches, else averaged individual doubles.
- **Triple threat:** tally counts every game; rating uses completed rounds only, decomposed
  into 3 pairwise mini-results into singles ELO at **K=12**; < 2 completed rounds = unrated.
- Ratings never touch point-level data. Caches are recomputed from finished matches on read.

## Approval machine
- Finish/save-final → `pending_approval`; logger auto-approves, others get chips.
  All approved **or** 24h deadline → `finished` (rated). Editing a pending match resets approvals.
- Delete: live → instant (any member). Finished → `delete_requested`, needs **all** players
  (no auto-approve); keeps counting toward ratings until fully approved, then hard-deleted.
- `check_deadlines()` (called on every request) auto-finalizes expired **finish** approvals only.

## Done
- Schema + groups + code uniqueness + isolation.
- Full rating engine incl. pairs and TT decomposition, unit-tested.
- Approval + delete-request state machine, unit-tested.
- All 5 tabs + player pages, server-rendered, hydrated by JS.
- Live polling (3s, pause on hidden), public "watch only" feed, global leaderboard.
- Log multi-editor: scoresheet grid ⇄ per-point board (15/30/40, deuce/adv, tiebreak, undo)
  and TT editor (pairing line, tally, per-game buttons, undo); start-new with serving-order
  picker + inline "+ New player" + win-prob bar; "already played" final-score grid.
- Approval / delete request cards with mini scoreboards + countdown; per-match story strip
  on live-scored matches; request-delete on every finished match.
- Clay theme, phone-first, no browser popups. Dockerfile (port 7860). 25 tests green.

## Not done / deliberate simplifications (`ponytail:` in code)
- **No rating_cache/pair_ratings tables** — rebuilt from history per read (tiny data, never stale).
  Upgrade path: materialize caches if a group's match count ever makes per-read rebuild slow.
- **No server-side accounts/sessions** — the code is the only auth; the read-only "watch"
  experience for public groups is a client-side state, not server-enforced. Real per-user
  auth is out of scope (v2).
- **Grid ⇄ per-point switch** preserves games in the primary direction (per-point → grid via
  prefill); grid → per-point starts fresh point tracking. Saving the grid clears point logs
  so the two entry modes never fight for a single match.
- **Serve/story stats** cover hold%/break%, break-points-saved, deuce points, longest streak
  and a coarse set-comeback figure; they are display-only and never affect ratings.

## Admin god-mode (Task A)
- Hidden console at **`/admin`** — no link from any user-facing page. Gated by one secret
  `ADMIN_KEY`. Wrong/missing key → generic 404 ("not found"), revealing nothing.
- **ADMIN_KEY location:** `.env` (gitignored) as `ADMIN_KEY=...`, also settable via env var.
  App reads it in `app._load_admin_key()` (env var wins, else `.env`, else a dev default).
  ADMIN_KEY: kept in .env (untracked), rotated after exposure check.
- Client keeps the key in `localStorage` (`rally_admin_key`) and sends it as the
  `X-Admin-Key` header on every admin request (`static/admin.js`). Inline key form, no popups.
- Capabilities: dashboard totals (groups/players/matches/live) + per-group cards
  (name, code, public/private, counts, live dot, created, last activity); per group —
  open as member, toggle public/private, regenerate code (old code dies), rename, delete
  (typed-name confirm, cascades that group only); players — rename, delete (typed confirm,
  cascades their matches); matches — edit sets/date/kind, delete instantly (bypasses
  approval), force-finish a pending approval, approve/cancel a delete request; create group.
- Every destructive action needs a typed inline confirm. Every admin action appends to the
  new `admin_log` table (ts, action, target), shown at the bottom of `/admin`. All changes
  flow through the normal per-group rating rebuild (recomputed on read, so never stale).
- Admin data helpers live in `db.py` (rename/regen/delete/cascade + `log_admin`/`admin_logs`);
  bypass lifecycle ops in `logic.py` (`admin_delete_match`, `admin_force_finish`,
  `admin_approve_delete`, `admin_cancel_delete`, `admin_edit_match`); routes in `app.py`
  under `/admin/api/...`, each guarded by `require_admin`.

## Production-safe database (Task B)
- Backend is chosen by **`DATABASE_URL`**: unset → local SQLite `tennis.db` (default, dev +
  all tests unchanged); `postgres://…`/`postgresql://…` → Postgres via SQLAlchemy + `psycopg`.
- Single cross-dialect schema in **`schema.py`** (SQLAlchemy Core `MetaData`, incl. `admin_log`);
  Postgres tables are created with `metadata.create_all()`. SQLite still bootstraps from the
  raw `db.SCHEMA` string (the in-memory test helpers depend on it); a drift-guard test keeps
  the two in sync (same tables + columns). Case-insensitive player uniqueness is a functional
  unique index on `lower(name)` in `schema.py` (mirrors SQLite's `COLLATE NOCASE`).
- Queries are shared: a ~40-line DBAPI shim in `db.py` (`_PGConn`/`_PGCursor`/`_Row`) adapts
  psycopg to the `sqlite3.Row`/cursor interface the existing raw SQL uses — `?`→`%s`, rows
  that support both `r["c"]` and `r[0]`, and `lastrowid` via `SELECT lastval()`. The SQLite
  connection path is byte-for-byte the original. `INTEGRITY_ERRORS` catches dup-name violations
  on either backend. Rebuild-from-history logic is unchanged and identical on both.
- Requirements add `sqlalchemy` + `psycopg[binary]`. `psycopg` is imported lazily/guarded, so
  SQLite dev + tests run without it installed.
- **Deploy:** Render web service from the repo `Dockerfile`; env vars `DATABASE_URL` (Supabase
  Postgres) and `ADMIN_KEY`. Nothing else. Postgres correctness is wired but not exercised
  live here — the smoke test `test_db_backend.py` compiles the schema for the Postgres dialect
  (no live PG), and asserts the metadata matches the SQLite SCHEMA.

## "Loading…" hang FIXED + deployed live (latest)
- **Root cause:** on the LANDING page only `auth.js`+`app.js` load (not `log.js`). `app.js` had a
  top-level `const TAB_INIT = {…, log: initLog, …}` — `initLog` (from log.js) was undefined there,
  so the line threw a ReferenceError that crashed `app.js` before the boot even ran → the
  "Loading…" placeholder was never replaced. Fix: `TAB_INIT` uses lazy arrow wrappers so those
  names resolve only at call time (a group page, where log.js is present).
- **Fail-open boot (Task 1):** `staleTokenGuard()` checks `/api/auth/me` and `Auth.signOut()`s on
  `signed_in:false`; every awaited boot fetch is wrapped in `raceTimeout(…,4s,fallback)`; boot has
  try/catch + a 4.5s backstop → always renders the sign-in view, never a stuck placeholder;
  once-guarded `startBoot` is triggered by readyState/`load`/`setTimeout(0)` (a late-added
  DOMContentLoaded listener doesn't fire in some embedded browsers). `initLanding` renders first,
  refreshes email in the background. `auth.js` `config()` is timeout-bounded too. Test: `test_boot.cjs`.
- **Cache-busting (Task 2):** `app.ASSET_V` = short md5 of the client JS/CSS, appended as
  `?v=<hash>` to every `<script>/<link>` (shell/landing/admin). New deploy → new hash → phones
  fetch fresh JS, not a stale cached copy.
- **Deploy (Task 4):** `deploy.py` file-uploads git-tracked files + `static/mockup-v9.jsx` to
  Vercel production `rally-scorer` (token from `VERCEL_TOKEN` env, never committed). Deployment
  `dpl_2NRqoqjqrWvtG8WiofnDQQta66kx` → READY. Verified LIVE at https://rally-scorer.vercel.app:
  fresh context shows the sign-in screen (Google/email — prod has Supabase keys); a junk token is
  cleared by the guard and the sign-in still renders. No console errors.

## 2026-07-26-FOUNDATION dispatch — BLOCKED at Task 0 & Task 4 (latest)
Only Task 1 (deploy) was actionable; the rest is halted pending Kabir. Nothing schema-related was
applied or committed.
- **Task 0 STOP — design files missing.** `rally-auth.jsx` and `rally-v11.jsx` (the approved
  spec for all following UI/identity work) are NOT in the repo folder — only `docs/mockup-v9.jsx`
  exists. Per the dispatch ("do not guess at the design") this halts Tasks 2 (freeze), 7 (gap
  inventory) and the design-conformance of 3/6. Kabir must add the two files.
- **Task 4 STOP — no Supabase MCP.** This environment has no Supabase MCP tools, and raw Postgres
  ports are unreachable from the sandbox. Per the dispatch, do NOT fall back to the app's silent
  auto-migration. So the live identity migration (Tasks 3-apply, 4, 5-backfill) cannot be applied
  or verified here — the SQL must be applied separately once decisions are made.
- **Task 1 DONE.** Redeployed current master `edb33ca` (deployment `dpl_265e89T15oC6gRCvin6qd2YmoQbY`,
  READY, cache-bust `b6d6a5e8d4`). Verified LIVE that the OAuth return surfaces every signed-out
  outcome: error→"Sign-in failed: access_denied — …", PKCE `?code=`→"…code_flow — Supabase
  returned a code, not a token", empty hash→"…empty — came back from Google with no token and no
  error". NOT covered: a COMPLETED Google login (real token accepted by the server) has never been
  exercised end to end — anonymous checks only hit the signed-out/error path.
- **Identity re-architecture is a real contradiction, not just work.** Today a player is a
  per-group INTEGER row (`players.group_id`, a human in 2 groups = 2 rows) linked to an auth user
  via `player_links(group_id, auth_sub, player_id)`; ratings are per-group. Task 3 wants ONE global
  player = `auth.users(id)` (uuid) with membership via `group_members`. Merging existing per-group
  rows into one global row is semantically ambiguous (which game_name wins? per-group ratings must
  be re-scoped) and re-keys every FK (match_players, tt_games, point_logs, approvals, matches.
  logger_player_id, player_links) on LIVE production data. Kabir must decide the merge before any
  SQL is finalized. Recorded in the deliverable's CONTRADICTIONS.

## Friends UI (2026-07-27) — deployed (latest)
Deployed dpl_GmFWEbNRZTSUEoA3h1Zu618A4HmH (READY), hash e8469aa122. 99 Python + Node green.
Pure CLIENT work — the friend ROUTES already existed (built in Phase 2), nothing new server-side:
  GET /api/players/search?q= · POST /api/friend/request {id|code} · POST /api/friend/accept {id} ·
  POST /api/friend/decline {id} · GET /api/friends {friends,pending}.
- **Task 1 (YOU card):** shows Name#CODE (from ME.code) with Copy (copies the code) and Share (Web
  Share API / clipboard fallback) of a `/?add=CODE` link; on boot that deep link lands on the Groups
  tab and prefills the search so the recipient can friend the sharer.
- **Task 2 (Add someone):** new section ABOVE groups — one search box (game name OR code) ->
  /api/players/search; each result shows game name (bold), real name, and #code; "Add friend" ->
  /api/friend/request {id}, row then reads "requested"; failure shows why (never a dead tap). Self is
  filtered out.
- **Task 3 (Friend requests):** section shown ONLY when /api/friends.pending is non-empty; each row
  Accept (/api/friend/accept) / Decline (/api/friend/decline); uses the pending list, no second source.
- **Task 4 (Friends):** section listing /api/friends.friends; empty state "No friends yet. Adding a
  friend is how you get someone into a match." Friends is the ONLY thing feeding the picker.
- **Task 5 (loop closed):** verified end-to-end locally (mock, two players): search Bob -> request ->
  Bob accepts -> Bob in /api/friends.friends and in /api/meta -> entering the Log tab refreshes meta ->
  Bob is a placeable chip -> both place -> Start becomes "▶ Start" (enabled). Note: the Log picker
  refreshes meta on tab (re)entry (and after start), not on a timer — the owner accepts on Groups then
  opens Log, which works; it won't live-update if you're already sitting on Log when a request is
  accepted elsewhere.
- Group membership still does NOT create a friendship (separate). No restyle — reused .card/.lbrow/.btn.
- **UNVERIFIED BY ME:** no signed-in session / no second device here — the real two-phone add/accept/
  decline and mobile Copy/Share (navigator.share) need his devices. Verified live only anonymously
  (app boots, search 200, the Friends UI code shipped at hash e8469aa122).

## Sign-in fail-open + group-delete re-render + boot perf (2026-07-27) — deployed (earlier)
Deployed dpl_ASEiYji9ZcJafbyrbxD9oYRei6xs (READY), hash 493c1a12ba. 97 Python + Node green.
- **Task 1 (sign-in dead end):** `auth.js config()` used to fall back to `{mode:"mock"}` on a 4s
  timeout or any thrown fetch AND cache it — so a slow/blocked request on a 2nd device showed a
  guest "Continue" button the supabase server refuses ("guest sign-in is disabled"). Fixed:
  config() now retries 3x with 10s per-attempt timeout + backoff, caches ONLY a real answer, and on
  failure returns `{mode:"error"}` (never mock, never cached). renderSignIn shows "Couldn't reach
  the server — retry" with a Retry button (resetConfig + re-render) — never a refused button. Guest
  "Continue" renders ONLY when the server says so: client_config now returns `guest`
  (= AUTH_MODE=="mock"); the client checks `cfg.guest`. Simulated a failing/blocked
  /api/auth/config: got the retry card, no guest button; simulated `{mode:"mock",guest:false}`: no
  guest button. Live: config sends guest:false, sign-in shows Continue with Google, no guest button.
- **Task 2 (delete wipes list):** `renderGroupRows` did `host.innerHTML=""` BEFORE the async
  /api/groups fetch, so a delete blanked the whole list until the refetch repopulated. Fixed: it's
  now atomic (fetch → build a fragment off-screen → `replaceChildren` in one swap, no blank), and
  confirmDeleteGroup/leaveGroup remove just the deleted card in place for instant feedback. Verified
  locally: deleting 1 of 2 leaves the survivor card visible throughout (1 immediately after, no wipe).
- **Task 3 (slow):** measured boot fetch order (local, mock). BEFORE: 3 SEQUENTIAL calls —
  /api/auth/me -> /api/me -> then renderTab -> /api/live (each of the first two is a server-side
  Supabase token-verify round trip in prod, blocking first content). Fixed: boot renders the tab
  immediately and resolves identity IN PARALLEL, so /api/me and /api/live now start together (was
  /api/live waiting for /api/me). One fewer sequential verify before first paint. No caching layer
  added. Tabs already render a skeleton synchronously then fill.
- **UNVERIFIED BY ME:** no Google session and no 2nd device here — the real second-device sign-in,
  the delete re-render on his device, and the prod cold-start/mobile boot latency need his devices.
  Local numbers are mock-mode (no cold start, instant verify) so they show the STRUCTURE, not prod ms.

## Group actions + court picker (2026-07-27) — deployed (earlier)
Deployed dpl_4pk6HnfYsZx91ATv6CZ8inBpsBVK (READY), hash cfc9044b77. 96 Python + Node green.
- **Task 3 (court picker dead tap) — ROOT CAUSE:** the roster chip's onclick was
  `rosterTap(${p.id})` with player ids now being UUID STRINGS → the attribute became malformed JS
  (`rosterTap(0d00-…)`) and threw on tap → the chip never placed. Same class as the openPlayer bug.
  Fixed by quoting: `rosterTap('${p.id}')` (also `ttAward('${id}')`, `ttPickSet(...,'${id}',...)`).
  The min-players rule was NOT the blocker — but it was silent, so `updateStartBtn` now STATES why
  the Start button is disabled ("add a friend to play singles/doubles/triple threat" when there
  aren't enough placeable people, or "place N players to start"). Never a dead tap.
- **Task 4:** /api/meta with no group = the player + accepted friends only; the signed-in player is
  ALWAYS included (verified: zero friends -> exactly one placeable chip, you).
- **Task 1 (leave):** new POST /api/group/<gid>/leave. A non-admin member leaves (removed from
  group_members, matches untouched). The ADMIN cannot leave (would orphan the group) -> 400 with a
  plain reason (hand over admin or delete); the client surfaces it. Server-enforced, not just UI.
- **Task 2 (delete in UI):** the Groups-tab card now shows Delete (admin only) behind an inline
  confirm stating matches are KEPT. Server /api/group/<gid>/delete is admin-only (403 direct for a
  non-admin, verified). Deleting keeps matches (group_id -> NULL + former_group_name).
- **Resilience (applied the recommended treatment):** loadRanks, the Live poller, and log.js
  loadEditor now use raceTimeout + an error/retry state — no tab can sit on "Loading…" (the class of
  fault behind the History hang). Removed the wrong "· This group" scope label on Ranks/History
  (now shows the real filter: a group name or "All groups").
- **UNVERIFIED BY ME:** the signed-in interactions (placing a chip, leave, delete) — no Google
  session in this env; confirmed by local mock runs + the suite. The /leave route existing and the
  picker/Start code shipping ARE verified live (anonymous). Needs the owner's device for the signed-in
  end-to-end.

## First-signed-in bug fixes (2026-07-27) — deployed (earlier)
Three faults from the owner's first live signed-in test, all SQLite-passed / Postgres-broke
divergences or a CSS selector miss. Deployed dpl_HGJtZ5ufoH83jYV8uqWqgXv35nr8 (READY), hash 7c97dc8db0.
- **BUG 1 — group create 500:** `db.create_group` inserted int `1` into the live BOOLEAN
  `groups.is_public`; psycopg rejects int→boolean → 500. SQLite (INTEGER column) accepted it, so
  tests missed it. Fixed: insert `True`; `set_public` now writes `bool(is_public)`. Route is
  POST `/api/group/create` (client + server agree; `/api/groups` is the GET list, hence the 405).
- **BUG 2 — History hang:** the signed-in branch of `/api/history` used
  `SELECT DISTINCT m.* ... ORDER BY COALESCE(finished_at, created_at)`. Postgres forbids a DISTINCT
  query ordered by an expression not in the select list → 500 (SQLite allowed it). Anonymous skips
  that branch (p is None), so it returned 200 and masked the bug. Fixed: dropped DISTINCT (a player
  is in match_players once per match). Also hardened `loadHistory` (raceTimeout + retry/error state)
  so a tab never sits on "Loading…".
- **BUG 3 — tab bar unstyled:** the SPA shell uses `<button>` for the tabs but style.css targeted
  `.tabs a`, so the buttons got default (boxy) chrome. Fixed: target `.tabs a,.tabs button` and
  strip border/background. Verified LIVE (border:none, transparent bg).
- **Also found (reported, NOT changed — out of the 3-bug scope):** `loadRanks` / `initLive` poll /
  log.js `loadEditor` have no try/catch (same stuck-placeholder risk if their endpoint ever errors —
  their endpoints have no DISTINCT/COALESCE hazard today); Ranks/History still show a leftover
  "· This group" scope label (data is global/correct); no client↔server route mismatches found.
- **UNVERIFIED BY ME:** BUG 1 & BUG 2 are Postgres-only and need a signed-in session to trigger the
  original 500s; this env has no Google creds and mock tokens don't verify against live Supabase, so
  those two live signed-in paths are confirmed only by code + local SQLite — needs the owner's device.

## CLEAN FOUNDATION — COMPLETE & DEPLOYED (Phase 2 A–D done) (earlier)
The clean-foundation rewrite is live. Suite GREEN (93 Python + boot/engine/sync Node). App boots on
the migrated Postgres and scores a match with group_id NULL.
- **Deployed:** dpl_C9rXw3BkR7EA7ijTiyJjpiUYhjY6 (READY), cache-bust `a966babada`. Live verify:
  `/` serves the SPA (not 500); `/api/me`, `/api/leaderboard` work against live PG; config=supabase;
  `/api/auth/player-id` returns a clean 401 (schema-correct — no dropped-column error).
- **Tests ported (Task C) — rewrites where a concept was removed, NOTHING silently deleted:**
  cache (in-process rating cache gone) -> rating correctness + global/?group= filter; admin (global
  god-mode rename/void/link/regen/player-cascade gone) -> per-GROUP admin guards + remaining
  key-gated god-mode (overview, match delete); auth/onboarding/names (admin-added players +
  player_links + per-group claim/link + private-name-hiding gone) -> self-serve global identity,
  friends-only picker, public-instant/private-request join; tennis (voided/restore gone) ->
  unapprove-rollback + dispute + delete-excludes, and finish-immediate -> finish-needs-approval.
  Coverage genuinely dropped only where the FEATURE is gone: player hard-delete cascade (no
  player-delete endpoint), match void/restore & admin relink (replaced by approval flow), per-group
  private-name-hiding. Doubles intra-side serve order is now uuid-ordered (live schema has no
  per-side order column) — serve test asserts the side-level invariant.
- **Still open (unchanged, do NOT touch): RLS is DISABLED on all live tables** — the public anon key
  can read/write every row. Owner-deferred hardening pass.
- **Not verifiable here:** a real signed-in Google/Supabase session (no creds in this env) — only
  anonymous/mock paths were exercised.

## CLEAN FOUNDATION — PHASE 2: Tasks A+B DONE & browser-verified (superseded by the section above)
Resume map. NOT deployed — the gate forbids deploy until the full suite is green (the ~83 old tests
are still red on the dead model). **Browser boot+score WORKS** (below).
- **VERIFIED IN-BROWSER (real uvicorn + fetch, mock mode):** `/` serves the SPA; a signed-in user
  lands on **Live with no group** (header "All groups", no gate). Friends-only court picker shows
  both players; a NULL-group singles match was started, scored, finished, approved by the other
  participant -> **status 'counted', group_id NULL**; History shows it (6-0, "Live-scored") and
  Ranks shows the applied ratings (+28 / -28). Task A (app.py routes) + Task B (static/app.js,
  static/log.js, templates/shell.html) COMPLETE and committed.
- **REMAINING — Task C (tests, BLOCKS DEPLOY):** the ~83 old tests (test_tennis/app/admin/auth/
  names/onboarding/one_live/signin/cache/consistency/db_backend/perf/ratings_dominance/ui_support)
  assume the dead integer/per-group model and are RED. Port them to the global-uuid model. Patterns
  proven to work (mirror the smoke test): create a player with `db.create_player(uuid, game_name)`;
  a match is scored via TestClient with bearer `auth.mint_mock_token(sub, email)` then
  POST /api/match/start {kind,side1,side2,group:null} -> point... -> finish -> other participant
  /approve -> status 'counted'. Use `db.SCHEMA` in-memory. Keep test_playerid green (8 pass).
  Cover: score-no-group, global vs ?group= rating filter, first-sign-in creates player+code,
  friends accepted-only picker (GET /api/meta with no group = self+accepted friends), group admin
  guards (403 for non-admin on /api/group/<gid>/*), count-only-when-all-approve, unapprove rolls
  back, freeze/resume need all participants.
- **REMAINING — Task D:** once the suite is green, run deploy.py (VERCEL_TOKEN in env), verify live
  boots (not 500) + report deploy id/readyState/hash.
- **Known cosmetic:** Ranks/History scope line still shows "· This group" (leftover RANK.scope/
  HIST.scope labels); data is global/correct. Fix the label to reflect window.FILTER.
- Old phase-1 resume map below is superseded by the above.
- Backend earlier resume detail (superseded):
- **DONE + verified this phase (committed):**
  - `app.py` FULLY rewritten to the global model (Task A). All routes are global `/api/*` with an
    optional `?group=<code>` filter. Verified via a TestClient smoke: first sign-in -> needs_name ->
    `/api/me/claim` (creates player + 5-char code); start a NULL-group singles match; score points;
    `/api/match/<id>/finish` -> pending_approval (logger auto-approves); other participant
    `/api/match/<id>/approve` -> **counted, group_id NULL**; `/unapprove` -> pending_approval
    (ratings roll back). App imports + boots at process level (require_schema passes on fresh SQLite).
  - `scoring.py` — serve_return_stats accepts group_id=None (global player page).
  - `templates/shell.html` — group-optional; served as the SPA; `window.GROUP` is null unless a group
    filter is active; `window.FILTER` = active group code or null; header is a switcher/filter.
  - KEY API CONTRACTS (the client must call these): GET `/api/me` -> {signed_in, player_id,
    player_name, player_real_name, code, needs_name?}; POST `/api/me/claim` {name, real_name};
    POST `/api/me/rename`; GET `/api/live|meta|leaderboard?mode=|history|player/<id>|match/<id>`
    (+ optional `?group=CODE`); POST `/api/match/start` {kind, side1, side2, rotation, group?} (logger
    = the token's player); POST `/api/match/<id>/{point,point/undo,sets,tt,tt/undo,date,finish,delete,
    approve,unapprove,dispute,freeze,resume}`; GET `/api/friends`; POST `/api/friend/{request,accept,
    decline}` {id|code}; GET `/api/players/search?q=`; GET `/api/groups`; POST `/api/group/create`
    {name}; POST `/api/group/join` {code} (public=instant, private=request); POST
    `/api/group/<gid>/{public,rename,code,admin,remove,delete,approve,decline}` (admin-only) + GET
    `/api/group/<gid>/requests`.
- **REMAINING — Task B (client, static/app.js + static/log.js):** swap EVERY `/g/${GROUP.code}/api/*`
  call to the global contract above via a helper like `G(path)` = `"/api"+path` + `?group=FILTER`
  when set. Specifics: (1) IDs are now UUID STRINGS — every `openPlayer(${p.id})` / `openPlayer(${r.id})`
  must become `openPlayer('${p.id}')` (quote the id). (2) `ensureIdentity()` -> GET `/api/me`;
  `chooseName()` -> POST `/api/me/claim`; `saveName()/editName` -> `/api/me/rename`. (3) `authGate()`
  -> drop the group gate: signed-in => full; signed-out => showSignInGate; no per-group READONLY.
  (4) `boot()` -> delete the `PAGE==="landing"` branch and `if(!GROUP)return`; always SPA; land on
  Live. DELETE initLanding/renderLanding/landJoin/landCreate and `templates/landing.html` usage.
  (5) tab loaders: initLive->`G('/live')`, loadRanks->`G('/leaderboard?mode='+RANK.mode)` (RANK.scope
  gone), loadHistory->`G('/history')`, openPlayer/openPlayerNoPush/renderPlayer date->`G('/player/'+pid)`
  / `G('/match/'+id+'/date')`. (6) Groups tab: `initGroups`->GET `/api/groups`; create/join->
  `/api/group/create|join`; flipPublic->`/api/group/<gid>/public`; YOU card uses `/api/me`.
  (7) `openSwitcher()` -> list the user's groups (from `/api/groups`) + "All groups"; picking sets
  `window.FILTER` and re-renders (a FILTER, navigates to `/` or `/g/<code>/live`). (8) router:
  `routeFromPath` parse `/<tab>` and `/g/<code>/<tab>`; `switchTab` pushState to `/<tab>` (or
  `/g/<code>/<tab>` when filtered). (9) log.js: `refreshMeta`->`G('/meta')`; `startPayload` add
  `group: window.FILTER||null` and drop `logger`; `startMatch`->`/api/match/start`; `loadEditor`->
  `G('/live')`; pt/ptUndo/sets/finish/delete/tt/played -> `/api/match/<mid>/...` and `/api/played`.
  Keep the fail-open boot + ASSET_V cache-bust.
- **REMAINING — Task C (tests):** the ~83 old tests assume the dead model and are RED. Port them to
  the global-uuid model (create_player(uuid,...), null-group matches, status='counted', approvals,
  friends, group admin). Keep test_playerid green (already ported, 8 pass). Add coverage:
  score-with-no-group, global vs ?group= rating filter, first-sign-in creates player+code, friends
  accepted-only picker, group admin guards, count-only-when-all-approve, unapprove rolls back,
  freeze/resume need all participants. Suite MUST be green before deploy.
- **REMAINING — Task D:** browser boot+score verify (mock mode), then deploy.py + live check.
- RLS still DISABLED on live (owner-deferred; do NOT touch).

## CLEAN FOUNDATION rewrite (2026-07-27, Option C) — PHASE 1 done, NOT deployed (earlier)
Live Postgres was rebuilt clean (global uuid identity; migration rally_clean_foundation, applied by
the orchestrator). The app code is being rewired to it. **This is partial — do NOT deploy until the
HTTP routes + client are rewired and a match can be scored over HTTP.**
- **DONE + self-tested (committed):**
  - `db.py` — full rewrite to the clean schema: global `players.id = auth.users.id` (uuid), `code`,
    `game_name`; `matches.group_id` NULLABLE; new status set (live/frozen/pending_approval/counted/
    disputed/deleted); friendships (one row/pair, a<b), name_history, group_members,
    group_join_requests, approvals, freeze_requests. Portable: uuids + codes generated in Python so
    ONE query path serves both the migrated Postgres and local SQLite. Code alphabet A-Z2-9 minus
    O,0,I,1,L. **No auto-migration** — `require_schema()` FAILS LOUD at startup if the DB isn't
    migrated (the old silent try/except ALTER path is deleted).
  - `logic.py` — new lifecycle: score with NO group; `finish` -> pending_approval (logger
    auto-approves); a match COUNTS only when every participant approves; withdrawing an approval on a
    counted match drops it to pending_approval and **rolls ratings back** (ratings recompute-on-read
    from status='counted' only); freeze/resume each need every participant. Self-tests green.
  - `auth_playerid.py` + `test_playerid.py` — reconciled to the new schema (players.id IS the auth
    id; dropped auth_id/password_set refs). App imports + validates the new schema at startup (boots
    at the process level).
- **REMAINING (next phase, large):** rewrite `app.py` (~40 routes still call old helpers /
  require_group; convert /g/<code>/api/* to global /api/* with an optional ?group= filter; /api/me
  creates a global player on first sign-in), `auth`/identity route, the client (`static/app.js`,
  `static/log.js` — swap all `/g/${GROUP.code}/api/*` to `/api/*`, make GROUP optional, delete the
  YOU/YOUR GROUPS landing gate so `/` serves the SPA on Live), `templates/shell.html` +
  `landing.html`, `schema.py`, and the ENTIRE old test suite (test_tennis/app/admin/auth/names/
  onboarding/one_live/signin/cache/consistency/db_backend/perf/ratings_dominance/ui_support — all
  assume the dead integer/per-group model and are currently red). Friends/groups-admin/approval-
  freeze-resume are implemented at the DATA layer; their HTTP routes + UI still need wiring.
- **RULES now enforced in the data layer:** membership != friendship (separate tables); court picker
  must read `db.accepted_friends` only; public group = instant join, private = `group_join_requests`
  the admin approves; delete group -> matches.group_id=NULL + former_group_name kept; count only on
  full approval; undo-approval rolls back; freeze/resume need all participants. RLS still DISABLED on
  live (owner-deferred; do not touch here).

## UI rebuild to approved mockup v9 (latest)
Rebuilt the drifted SCREENS to match `docs/mockup-v9.jsx` (the palette already matched; the
layouts did not). Full drift audit in `docs/drift-inventory.md`. Suite: 81 Python + boot/engine/
sync Node green.
- **Landing / Groups (Task 2).** Groups tab `/g/<code>/groups` now renders the mockup: a **YOU
  card** (avatar, game name + gold YOU badge, real-name subtext, "claimed on this phone",
  "Change"); **YOUR GROUPS** as one card per group (🎾 name + green "· current", "code XXXX ·
  private/public", Make public/private toggle); a final card with tap-to-expand "+ Create a
  group" / "+ Join another group". The group-agnostic **landing `/`** got the same card system
  (its YOU card shows email + Sign out — no per-group player exists there). All prior behaviour
  kept (join/create/switch/visibility/sign-out); no group content before sign-in.
- **Name editor (Task 4).** The YOU-card "Change" opens the existing self-serve editor (game
  name bold + real name subtext, uniqueness check + error preserved) — `renderYouCard` →
  `editName`/`saveName` → `/api/rename-me`. Email + sign-out live inside that editor.
- **Live (Task 3).** Win-prob is now one segmented track + a caption ("updates live with every
  point, from ratings + current score" / "…games won"); 3-way TT bar is a single green/gold/line
  bar. `winBar` in app.js; `.wpwrap/.wplabels/.wptrack/.wpseg/.wpcap` in style.css.
- **Log (Task 3).** Chemistry rows are the mockup's boxed team-coloured rows ("TEAM n ·
  Chemistry · score / Unexplored — N more… / pick both players"); both team rows always show for
  doubles. `renderChem` in log.js; `.chembox/.chemteam/.chemlab`.
- **Player (Task 3).** Back button reads "← Ranks" (was "← Back").
- **Ranks / History / filter sheets:** already matched structurally — unchanged (Ranks keeps its
  pinned clay YOU card, an intentional enhancement not in the mockup).
- **Triple Threat direct scoring (Task 5).** The live TT editor gains a **"+ player" button per
  rotation player** that awards a game immediately — no rotation confirmation needed. The Yes/No
  rotation confirm still exists but no longer BLOCKS scoring. Serve degrades cleanly: an award
  made while the rotation is confirmed (e.g. game 1 from placement) sends server/receiver; an
  award made while the rotation is **unconfirmed sends `{winner}` only** → `tt_games.
  server_player_id` NULL, no serve attribution (never guesses). A "Set who's serving" link
  re-confirms. `ttAward`/`commitTTGame`/`EDIT.rotKnown` in log.js. **No schema change** —
  `tt_games.server_player_id`/`receiver_player_id` were already nullable and `/tt` already passed
  `d.get("server")`. Test: `test_tt_direct_award_without_confirmed_rotation` in test_tennis.py.
- **Permanent rule reaffirmed:** the two surfaces (landing `/` vs Groups tab) map to the
  mockup's single GroupsTab; the YOU-card name editor only exists in-group (identity is
  per-group via player_links).

## Sign-in outcomes surfaced + refresh-token sessions (NOT deployed at time of writing)
- **Permanent rule: no sign-in outcome is ever swallowed.** Every failure path puts a reason on
  screen; the sign-in card never silently reappears.
- **OAuth return recorded (auth.js `captureOAuthReturn`).** On return from Supabase it inspects
  BOTH the URL hash and query, then records `Auth.lastReturn()`: token→`{ok:true}`; error/
  error_code/error_description→`{ok:false,error,description}`; a bare `?code=` (PKCE — we only do
  implicit)→`{ok:false,error:"code_flow"}`; came-back-with-neither→`{ok:false,error:"empty"}`.
  Hash/query are stripped via `history.replaceState` only AFTER recording; the outcome is
  persisted in `sessionStorage` (try/catch-safe) so it survives the reload. `renderSignIn` shows
  a one-time muted red line "Sign-in failed: <error> — <description>" (HTML-escaped, ≤200 chars).
- **Server-rejected fresh token surfaced.** If `/api/auth/me` says `signed_in:false` while
  `lastReturn().ok===true` (token minted THIS attempt), the guard records "Signed in with Google,
  but the server rejected the session." A plain expired token still signs out silently.
- **Refresh-token flow (sessions survive past ~1h).** `captureOAuthReturn` stores `refresh_token`
  (`rally_refresh`). `Auth.refreshSession()` POSTs `${SUPABASE_URL}/auth/v1/token?grant_type=
  refresh_token` (anon key as `apikey`); success→store new tokens, failure→clear both. The stale-
  token guard, on `signed_in:false` WITH a refresh token, tries `refreshSession()` ONCE (bounded
  by `raceTimeout`) and re-checks before signing out. No refresh token → behaves exactly as before.
- **Boot fails open even without auth.js.** `failOpen()` now writes a "Rally couldn't start — tap
  to retry" card (+Reload button) when `window.Auth` is missing or `showSignInGate` throws —
  never a blank host.
- **No group name before sign-in.** `shell.html` renders a neutral header (Rally / "tennis
  scorer"); `setHeaderName()` swaps in the group name + code only after `/api/me` confirms a
  signed-in session.
- Files: `static/auth.js`, `static/app.js`, `templates/shell.html`. Tests: `test_boot.cjs`
  extended (refresh-succeeds→kept, refresh-fails→clean sign-out no hang, no-refresh→as-before,
  auth-missing→error card, fresh-token-reject→message). Suite: 80 Python + boot/engine/sync Node.

## Speed/UI revamp (in progress — read docs/mockup-v9.jsx, the owner-approved reference)
- **Task 0 (done):** `docs/mockup-v9.jsx` (51,461 bytes) committed as the permanent UI reference.
- **Task 1 (done): SPA shell.** All `/g/<code>/<tab>` + `/player/<id>` routes serve ONE
  `templates/shell.html`; the JS router (`app.js`) switches tabs client-side (keep-all-panels
  model, unique ids per tab), `history.pushState` for shareable URLs, `popstate` back button.
  Measured tab switch 1–10ms, no page reload. Pollers are per-active-tab (`clearPollers`).
  Old per-tab templates (live/leaderboard/log/groups/history/player.html) are now DEAD (shell
  replaces them) — left in the repo, safe to delete later.
- **Task 4 (done): player overlay.** Tapping a rank row → `openPlayer(id)` fetches
  `GET /g/<code>/api/player/<id>` and renders PlayerStats as an in-app overlay (back button +
  URL). Never self-vs-self. (Was broken because the old route/build; now an overlay.)
- **Task 5 (done): FunnelDrawer.** Right-side drawer (Mode/Kind + Who checkboxes + Apply) on
  Ranks and History; filters change the list; History `scope=everyone` aggregates public groups.
- **Task 2 (done):** in-process rating cache keyed by `groups.ratings_rev` (bumped only on
  rating-affecting writes). ~721x faster reads; `test_cache.py` proves cached==fresh + invalidation.
- **Task 3 (done):** Postgres cold-start init cut from ~14 round-trips to 1 (presence check);
  SQLAlchemy/psycopg lazy. Local import ~0.7s (FastAPI floor); Vercel container spin-up is platform.
- **Task 6 (done):** one live match/player enforced in `start_match` (named error); past results
  exempt; picker greys busy players. `test_one_live.py`.
- **Task 7 (done):** Live cards 'KIND · started H:MM' + LIVE pill; court chips above court; Ranks
  rating colored. Rest already matched the mockup.
- **Task 4 (complete):** tapping a player on Ranks, **Live cards, and History cards** opens the
  overlay (`pLink`). Log picker chips PLACE players (mockup behavior), not navigate.
- **Task 8 (done):** hand-QA — tab switches 1.8–5ms; score singles + undo; player pages from
  every surface; filters change results; one-live enforced; no console errors.
- **Known deviations (not fixed):** (1) Live TT card shows tally + pairing + 'Game N · X sits out'
  but NOT the running within-game '30 · 40' point score — TT persists only completed games, not
  sub-game points (the scorer sees live points locally in the Log editor). (2) Old per-tab
  templates + player.html are dead (shell replaces them), left in repo.

## V2 status: COMPLETE + names/sign-in revamp (Tasks 0–8, onboarding, names+sign-in)
All built, tested, committed. 73 Python + 2 Node tests green. Deploy needs env vars
`DATABASE_URL`, `ADMIN_KEY`, and (for real sign-in) `SUPABASE_URL` + `SUPABASE_ANON_KEY`.

### Names + clean sign-in (latest)
- **Two names per player.** `players.name` = GAME NAME (bold handle, unique per group);
  `players.real_name` = optional REAL NAME (subtext, may duplicate). Rendered as a name block
  everywhere (Ranks, Live, History, player page, court picker, account card): game name on top,
  real name smaller/muted under it, nothing when real name is blank. Win-prob bars use the game
  name only (compact) — a deliberate interpretation.
- **Self-serve, editable any time.** Onboarding = one screen, two fields (game required+unique,
  real optional, real pre-filled from provider via `/api/auth/me` `name`). `POST /api/claim-name`
  {name, real_name}. Users rename BOTH from the account card → `POST /g/<code>/api/rename-me`
  (no admin, no cooldown; propagates everywhere since all views read the current player row).
  Admin still edits both via `/admin` rename (name + real_name). Removed all "only an admin can
  change" wording. `players.real_name` column + migration.
- **Clean sign-in.** Fallback (no Supabase keys): the screen is ONE "Continue" button — no
  Google/email/OTP, no dev code ever. It creates a UNIQUE PER-DEVICE identity: `auth.js`
  generates+stores `rally_device` (crypto.randomUUID) and `POST /api/auth/guest {device_id}`
  mints `guest:<id>`; same device always returns as the same player, two devices = two players.
  `/api/auth/guest` is 400 in supabase mode. Real mode: "Continue with Google" (Supabase OAuth
  redirect) + "Continue with email" (code typed, never shown). Tests: `test_names.py` (6),
  `test_signin.py` (4). QA verified by hand in a phone browser (all 6 journey checks passed).

### Onboarding fix (latest — reverses "admin-adds-players")
- **Sign-in is always first.** A private group shows only the sign-in screen when signed out
  and never reveals its name (header shows "Rally"; `window.GROUP.name` empty; page HTML omits
  it). A **public** group is viewable read-only signed out (name shown, "Viewing read-only ·
  Sign in to play" banner; Log tab gated). Header name is filled by JS from `/g/<code>/api/me`
  (authed) once signed in.
- **Self-serve names.** After sign-in, if unlinked, a "Choose your name" screen (text field
  "The name your friends will see") CREATES a player and links it — endpoint
  `POST /g/<code>/api/claim-name` (rejects empty→400, duplicate→409). Secondary "I'm already in
  this group" link opens the existing-player picker (`/api/link`). Locked once set (re-claim →
  409). Anyone with the code can join+name; code is the only gate. Admins still add/rename/
  delete/link/unlink in `/admin`.
- **Identity visible.** Groups account card shows avatar + display name + email + group; own
  Ranks card pinned; YOU badge follows the link.
- **Real Google OAuth.** `auth.js` redirects to `${SUPABASE_URL}/auth/v1/authorize?provider=
  google&redirect_to=<app>` in supabase mode and captures the returned `#access_token`; falls
  back to the local mock when keys are absent. README has the Google Cloud + Supabase setup steps.
- Files: `app.py` (/api/me group_name, /api/claim-name, private-name hidden in page), `app.js`
  (authGate read-only/private split, chooseName, header fill, account avatar), `auth.js` (OAuth),
  `templates/base.html` (conditional header), `static/style.css`. Tests: `test_onboarding.py` (7).

## V2 progress (task-by-task, newest first)
- **Task 6 + 8 — Full V2 UI + QA (done).** Rebuilt all tabs + player page to the rally-v9 spec
  (clay, 5 tabs). Sign-in gate (auth.js) → "Which player are you?" pick (locked). LOG: court
  picker (`log.js`) — clay court, slots per format, tap-to-fill/remove, first-serve 🎾, doubles
  chemistry rows from pair ratings; Start greys to "A match is already live" (one at a time,
  rejects busy players). Live editor wires engine.js + sync.js: instant DOM per tap, background
  sync with `● synced / ○ saving…` chip, hydrate-once, no reloads; per-point default + Set-scores
  grid; TT scored per-game with the **confirm-rotation** Yes/No flow (stores confirmed
  server/receiver → drives serve attribution). Already-played grid + native date/time. LIVE:
  read-only broadcast cards (all 3 formats) with inline 🎾 server + 2-way/3-way win-prob bars;
  empty sections render nothing; polls. RANKS: search + funnel, 0-based display (Elo−1200),
  green live dot, pinned own card, "n of 5". PLAYER page 0-based. HISTORY: funnel + inline
  date/time edit (`/date`). GROUPS: account card, tap-to-switch rows, member public/private flip.
  Server support (`6a`): `/api/meta`, win-prob in live feed, `tt_games.receiver_player_id`,
  no-cache header on /static (fresh assets after deploy). Tests: `test_ui_support.py` (4).
  QA verified in-browser: mock Google sign-in, link-as-Ann, full singles (6-0 → +28 with
  point-dominance), TT Yes + No rotation paths, live win-prob, ranks 0-based, groups flip,
  sync chip + data-lands-on-retry.
- **Task 4 — Supabase auth (backend + client module done; sign-in UI wires into Task 6).**
  `auth.py` provider: Supabase (Google + email OTP) when `SUPABASE_URL`+`SUPABASE_ANON_KEY`
  set, else a self-contained **local mock** (email OTP returns `dev_code`; Google = fixed
  test user). Tokens are mock-HMAC (verified locally) or real Supabase (verified via
  `/auth/v1/user`). `require_user` gates EVERY write (401 if not signed in); reads/public
  viewing are open. New tables `users` + `player_links` (UNIQUE(group_id, auth_sub)). Endpoints:
  `/api/auth/config|email/start|email/verify|google|me`, `/g/<code>/api/me`, `/g/<code>/api/link`
  (pick-once, locked → 409 on relink), admin `/admin/api/group/<gid>/link|unlink` for relink.
  Player creation is **admin-only**: `/g/<code>/api/player` needs a valid `X-Admin-Key` (group
  app never sends it → 403 "Players are added by the admin."). Client `static/auth.js` (token
  storage, inline sign-in screen, no popups). Existing test clients send a default mock bearer +
  admin key. Tests: `test_auth.py` (7). README documents the env vars (untracked). 52 Python green.
- **Task 2 — Speed (core done; UI wiring pending with Task 6).**
  - 2a client scoring engine `static/engine.js` — full tennis rules (0/15/30/40, deuce/Ad,
    games, flexible sets, tiebreaks, undo) + Triple-Threat game/rotation. Mirrors `scoring.py`
    exactly. Node test `test_engine.cjs`.
  - 2b background sync queue `static/sync.js` — FIFO, async retry + exponential backoff,
    'synced'/'saving' status callback, injectable fetch. Node test `test_sync.cjs`
    (survives a failing POST, retries, preserves order, backoff 100/200/400/800).
  - 2c cold-start: SQLAlchemy + psycopg confirmed **lazy** (not imported at module load;
    verified via `sys.modules`); uvicorn import lazy. App import ~630ms, dominated by FastAPI.
    Per-request rating recompute kept intentionally (tiny friend-group data); signature-
    invalidated in-process cache is the documented upgrade path.
  - 2d consistency `test_consistency.py` — same points through JS engine ≡ Python scorer ≡
    server replay (stored `match_sets`), all identical.
  - 2e perf `test_perf.py` — leaderboard/live/history/point endpoints all <300ms locally;
    queue-survives-failure covered by the sync Node test.
  - **Pending (needs the Task 6 UI):** wiring engine+queue into live scoring with the status
    chip, hydrate-once-on-load, partial DOM updates, no mid-match reloads.
- **Task 5 — Approvals reversed (done).** Removed the all-players approval machine + request
  cards. Match statuses are now just `live`→`finished`; **finishing counts immediately**
  (ratings/leaderboard/history). Deletes are immediate **soft-deletes** (`matches.deleted`),
  hidden everywhere and excluded from recompute; admin can **restore**. Admin also gains
  **void/unvoid** (`matches.voided` — kept but excluded from recompute-on-read). New columns
  `voided`/`deleted` added to SCHEMA + schema.py + an idempotent `_migrate()` for existing
  DBs. Rating query = `status='finished' AND voided=0 AND deleted=0`. admin_log records
  void/unvoid/restore/delete. Admin routes: `/void /unvoid /restore` (replaced
  force-finish/approve-delete/cancel-delete); admin.js updated. Existing approval tests
  rewritten to the instant model (43 green).
- **Task 3 — White-line/overscroll fix (done).** `theme-color=#A94E2F`; sand background on
  BOTH `html` and `body`; `overscroll-behavior-y:none` (+ `-webkit-`). Verified via computed
  styles in-browser (html+body bg = sand, overscroll = none) → no white flash on scroll/fling.
- **Task 7 — Rating point-dominance (done).** Live-scored singles/doubles get a bounded
  ±15% delta multiplier from the winner's share of total points (`ratings.dominance_multiplier`,
  neutral at share 0.75); it scales magnitude, never flips the result. Typed matches keep
  margin-multiplier only (no `points` key). Doubles scaling applies to both individual and
  pair deltas. `db._match_to_dict` supplies point totals from `point_logs`. Tests:
  `test_ratings_dominance.py`.
- **Task 1 — Collaborator (done).** Invited `soumikdasgupta` (write) to the GitHub repo.
- **Task 0 — SQL portability (done).** `players_of` now `ORDER BY LOWER(name)`; schema DDL
  `COLLATE NOCASE` annotated SQLite-dev-only (Postgres uses the `LOWER(name)` unique index).

## Out of scope (v2 parking lot)
Accounts; async challenges + duo requests; individual doubles return attribution (deuce/ad
court); rating decay; notifications; cross-group rating math.
