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

## V2 progress (task-by-task, newest first)
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
