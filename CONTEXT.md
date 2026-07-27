# CONTEXT.md — Rally (tennis scorer)

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

## CLEAN FOUNDATION — COMPLETE & DEPLOYED (Phase 2 A–D done) (latest)
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
