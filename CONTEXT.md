# CONTEXT.md — tennis-scores

## State
Working, tested, verified end-to-end in a browser. Built locally, **not deployed**.

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

## Out of scope (v2 parking lot)
Accounts; async challenges + duo requests; individual doubles return attribution (deuce/ad
court); rating decay; notifications; cross-group rating math.
