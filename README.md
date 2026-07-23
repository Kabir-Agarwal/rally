# 🎾 Rally — tennis scorer

Phone-first web app for friend groups to track tennis matches and rank players.
No accounts — a group is a private space reached by one 6-char code. **Matches are the
only truth**; every rating and stat is recomputed from match history, per group.

FastAPI + SQLite + Jinja2 + vanilla JS. One Docker image, port 7860 (Hugging Face Space
ready). No browser popups anywhere — all inputs are inline.

## Run

```bash
python -m venv .venv && . .venv/Scripts/activate      # (Windows) or: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --port 7860
# open http://127.0.0.1:7860
```

Tests: `pytest -q`. Each core module also self-checks: `python ratings.py`,
`python logic.py`, `python scoring.py`, `python db.py`.

Docker:

```bash
docker build -t rally . && docker run -p 7860:7860 --env-file .env rally
```

## Admin (god-mode)

A hidden console lives at **`/admin`** — no link points to it anywhere in the app.
It is gated by one secret `ADMIN_KEY` (kept in `.env` / an env var, never shown in the UI;
the value is recorded in `CONTEXT.md`). A wrong or missing key returns a generic *not found*.

With the key, an admin sees a dashboard (totals + a card per group with code, public/private,
counts, live dot, dates) and can: open any group as a member, toggle public/private,
regenerate a group's code (invalidating the old one), rename or delete a group, rename or
delete players (cascading their matches), and per match — edit sets/date/kind, delete
instantly, force-finish a pending approval, or approve/cancel a delete request. Every
destructive action needs a typed inline confirm, every action is written to an `admin_log`
shown at the bottom of `/admin`, and every data change flows through the normal per-group
rating rebuild.

## Groups & permissions

- The **code in the URL is the capability**: anyone who enters a group's 6-char code
  (A–Z, 2–9) is a member and can see and update everything.
- `is_public` (a big toggle any member can flip): **public** → anyone with the link can
  watch read-only and the group's players appear on the global leaderboard; **private** →
  members only, invisible to the global feeds.
- Landing = Create (name → code shown big) or Join (code → straight into the group).
  There is no group-browsing endpoint.
- The device remembers joined groups and "which player am I" (per group) in
  `localStorage`. The header opens an Instagram-style quick switcher; full management is on
  the Groups tab.
- The same person in two groups is two separate player records. A player can be in several
  live matches at once.

## Rating engine (`ratings.py`, pure & unit-tested)

Singles and doubles each have their own ELO. Start **1200**, **K=32**,
**MIN_MATCHES=5** per mode to be ranked (provisional below, shown "N of 5"); the rating
itself always reflects the whole history.

**Expected score:** `P(A) = 1 / (1 + 10^((Rb − Ra) / 400))`

**Margin multiplier:** `share` = winner's fraction of total games,
`M = clamp(0.75 + 3·(share − 0.5), 0.75, 1.5)`, and `K_eff = K·M`. Draws use `M = 1`.

**Winner of a match:** sets won → total games → draw (0.5 each). 0-0 sets are ignored.
Formats are 1–5 sets. Ratings apply at each match's finish/approval moment, in finish order.

Worked example — equal players, one set **6-4**:
`share = 6/10 = 0.6 → M = 0.75 + 3·0.1 = 1.05`. Winner:
`Δ = 32·1.05·(1 − 0.5) = +16.8` → **1216.8** / loser **1183.2**.

Worked example — **6-0 6-0**: `share = 12/12 = 1.0 → M = 1.5` (the cap).
**7-6 7-6**: `share = 14/26 ≈ 0.538 → M ≈ 0.865` (near the floor).

### Doubles
Team rating = average of the two partners. The team delta is computed once; **each
partner moves by the full delta** (not half).

### Pair ratings (`pair_ratings`)
Every doubles duo also has its own ELO (1200, K=32, same margin), moved **only by that
duo's matches, as a unit** (provisional under 3 pair matches). A player page lists a pair
rating per partner. Win-probability uses pair ratings when **both** duos have 3+ matches,
otherwise averaged individual doubles ratings.

### Triple threat (`tt`)
Three players in rotation order. Game cycle: G1 P1 serves v P2 (P3 sits), G2 P2 v P3,
G3 P3 v P1, repeating so serve/return/sit stay balanced. The scorer taps the game winner;
the running tally is the **session result** (ties allowed, and it counts *every* game).

Rated **gently**: only games in *completed rounds* count. A completed round is decomposed
into 3 pairwise mini-results — (P1,P2), (P2,P3), (P3,P1) — where win share = result and
game share = margin, applied into singles ELO at **K=12**. Fewer than 2 completed rounds =
unrated. The UI states "rates completed rounds only".

Ratings **never** use point-level data (fairness across entry modes). The win-probability
bar (ball marker) is computed from the formulas above only.

## Approval state machine (`logic.py`)

- Finishing a match (or saving a final score) → `pending_approval`. The logger's player
  auto-approves; everyone else gets an approve chip. **All approved OR 24h deadline** →
  `finished` + rated. Editing a pending match resets approvals.
- **Delete:** live matches are deletable instantly by any member. Any finished match can
  get a delete request needing approval from **all** its players (no auto-approve) — it
  keeps counting toward ratings until fully approved.
- Request cards sit at the top of History: clay-gradient header, a mini scoreboard inside
  (avatars, set cells, 🏆 on the winner), per-player approve chips, and a countdown. Never
  plain text, never "def.".
- Live matches never expire — pause across days, all sets editable until finished.

## Serving (positional, no questions)

Singles: Player 1 serves first, alternating. Doubles: T1-pick1, T2-pick1, T1-pick2,
T2-pick2 per game (standard tiebreak rotation). Pickers say "pick in serving order" and
show serving-order number badges (1-2 / 1-4 / 1-3). Per-point and TT boards show the
current server's name with 🎾.

## Screens

Bottom tab bar: **Live** (home) · **Leaderboard** · **Log match** · **Groups** ·
**History**, plus player pages reached by tapping a leaderboard row. Live views poll
`/g/<code>/api/live` and `/api/match/<id>` every 3s and pause on a hidden tab; public
groups are readable without membership.

## Data model

`groups, players, matches, match_players, match_sets, tt_games, point_logs, approvals`
(all group-scoped). Ratings are rebuilt from finished matches on read rather than cached —
friend-group history is tiny, so a full rebuild can never go stale. See `CONTEXT.md`.
