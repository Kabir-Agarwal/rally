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

## V2 status: COMPLETE + onboarding revamp (Tasks 0–8 + onboarding fix)
All v2 tasks built, tested, committed. 63 Python + 2 Node tests green. Deploy needs env vars
`DATABASE_URL`, `ADMIN_KEY`, and (for real sign-in) `SUPABASE_URL` + `SUPABASE_ANON_KEY`.

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
