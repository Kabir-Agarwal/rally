# Screen-by-screen drift inventory — app vs approved mockup (docs/mockup-v9.jsx)

Palette/tokens already match. This lists LAYOUT/structure/wording drift, per screen.
"App" = server-rendered HTML + vanilla JS (static/app.js, static/log.js, templates/*).

## 0. Two surfaces map to the mockup's one GroupsTab
- The mockup is a single-group SPA. The real app splits identity/groups across TWO surfaces:
  - **Landing `/`** (templates/landing.html + app.js `renderLanding`): group-agnostic home,
    shown when signed in but not inside a group. No per-group player exists here.
  - **Groups tab `/g/<code>/groups`** (app.js `initGroups`): inside a group, has the per-group
    player identity (`ME.player_name` / `real_name`). This is where the mockup's YOU card with a
    name editor belongs.

## 1. Landing / Groups  (biggest drift — Task 2 + 4)
- MOCKUP: **YOU card** (circular avatar w/ initial, display name, gold "YOU" badge, muted
  "claimed on this phone", "Change" button). **YOUR GROUPS** = one Card PER group (🎾 name +
  green " · current" on the active one, "code XXXXXX · private/public", ghost "Make public/Make
  private" button). Final Card with tap-to-expand "+ Create a group" and "+ Join another group".
- APP Groups tab today: "Account" title + account card (40px avatar, game+real name,
  "email · in group", **Edit name** + Sign out buttons); a "This group" card with a big dashed
  code box; "Your groups" as thin `.grouprow`s (not cards), Public/Private toggle + ✓; one
  always-open card with Create row + Join row + share box.
  → Drift: no YOU badge, no "claimed on this phone", groups are rows not cards, no green
  "· current" marker, create/join always-open (mockup taps to expand), extra "This group" card.
- APP landing today: plain "Your groups" `.lbrow` list (name+code); separate "Join a group"
  card; separate "Create a group" card; email + sign-out card.
  → Drift: entirely pre-card style; no YOU card, groups not individual cards, create/join split
  into two always-open cards.

## 2. Live
- MOCKUP: "Live now"; Singles/Doubles score-grid cards (sand header "KIND · started TIME" +
  LIVE pill; stacked names w/ 🎾 server; set columns; clay pts box; **2-way win-prob bar** green
  fill on line track, % each end, **caption "updates live with every point, from ratings +
  current score"**); **TT live card** (tally games-won, "Soumik 🎾 … Riya", **live point score
  "30 · 40"**, "Game N · X sits out", **3-way bar** green/gold/line w/ 3 %, caption "…ratings +
  games won"); "From public groups — watch only" only when non-empty.
- APP today (`broadcastCard`/`winBar`): header, 🎾 server, set cols, pts box all present. Public
  section already conditional.
  → Drift: (a) win-prob bars have **no caption line**; (b) TT card shows **no live point score**
  (known deviation — TT persists whole games only, not sub-game points); (c) 3-way bar is three
  sand name+pct segments, **not** a single green/gold/line bar; (d) 2-way bar uses team1/team2
  colors, mockup uses green-on-line.

## 3. Ranks
- MOCKUP: search + funnel (▼ 44×44); "Mode · scope" line; card of rows (rank#, avatar, name +
  online dot, "tap for stats", signed rating colored); "MINIMUM 5 MATCHES" section (rank "–",
  rating + "n of 5" pill).
- APP today (`renderRanks`): all present; ADDS a pinned clay "YOU" card (`youcard`) above the
  list (enhancement, not in mockup).
  → Drift: essentially aligned. Keep pinned YOU card. No structural change needed.

## 4. Log
- MOCKUP: seg (Singles/Doubles/Triple threat); instruction line; **CourtPicker** — player chips
  ABOVE a clay court; dashed drop-zone slots arranged by side with "TEAM 2 / TEAM 1 (you)" (or
  "SIDE 2 / SIDE 1 (you)") labels + a dashed net; TT court = RECEIVES / (net) / SERVES 🎾 + a
  benched "SITS OUT · NEXT IN"; 🎾 marks first serve; boxed **chemistry rows** per team (TEAM
  color, score or "Unexplored — N more…"); "Someone missing?…admin" note; Start (greys to "A
  match is already live"). "Update the live match": per-point editor w/ "Per point / Set scores"
  toggle, or TTEditor. "Already played? Final score".
- APP today (`log.js`): seg; `.court` grid w/ `.cslot`s (labels "Serves 🎾/Receives",
  "Team 1 · deuce/ad…", "Sits out"); roster chips BELOW isn't — chips are above court; chem rows
  are inline text (`.chemrow`), not boxed; Start greys correctly; point/TT editors present;
  played card present.
  → Drift: (a) slot labels + side headers differ from mockup ("TEAM 2/TEAM 1 (you)", TT
  "RECEIVES/SERVES 🎾/SITS OUT · NEXT IN"); (b) chemistry is inline text not the boxed
  team-colored rows; (c) point editor toggle exists but is a lone "Set scores" button, mockup
  shows a 2-up "Per point / Set scores" segmented control.

## 5. History
- MOCKUP: "History · mode · scope" + funnel; each row a Card: "A  —  6–4 · 3–6 · 7–5  —  B",
  muted "date · kind" + ✎ edit → inline **date + time** inputs + Save.
- APP today (`historyCard`): mtitle (side1 "vs" side2 with 🏆 winner), sheet of set columns,
  "KIND · when ✎", inline **datetime-local** edit, plus a story line (enhancement).
  → Drift: app shows sets as a column grid + "vs" + 🏆; mockup shows the score as one centered
  text string. App uses a single datetime-local; mockup uses separate date+time. Keep app's
  richer winner/story info; align header wording (already "· mode · scope").

## 6. Player detail
- MOCKUP: "← Ranks" back; summary card (big avatar, name + dot + YOU, "5W · 3L · last 5: W W L
  W L" colored, Singles/Doubles + "n of 5" pill); PAIR RATINGS ("with X" +score n/3); SERVE &
  RETURN (Hold %, Break %, "from N live-scored matches"); MATCHES.
- APP today (`renderPlayer`): same structure; back button reads **"← Back"** not "← Ranks".
  → Drift: back label only. Otherwise aligned.

## 7. Filter sheets
- MOCKUP: right drawer "Filters"; MODE/Kind checkbox group (rounded-square check); WHO group
  (This group / Everyone); Apply.
- APP today (`openFunnel`): right `.drawer` "Filters"; Mode/Kind `.fg`; Who `.fg`; Apply; `.fcheck`
  w/ `.fbox` check. → Aligned. No change needed.

## Screens present in one but not the other
- App-only (keep): /admin console, read-only public banner, "choose your name" gate, sync chip,
  history story line, pinned YOU card on Ranks.
- Mockup-only: none that the app lacks structurally.

## Task 5 feasibility (checked in code, no contradiction)
- `tt_games.server_player_id` / `receiver_player_id` are **nullable** (db.py) and
  `logic.log_tt_game(con, mid, server=None, winner, receiver=None)` already accepts nulls; the
  `/tt` route passes `d.get("server")`/`d.get("receiver")`. The next-game pairing is computed by
  `scoring.tt_pairing(rotation, game_index)` from the game COUNT, not stored server. So a point
  awarded without a confirmed rotation stores winner only (no serve attribution) and degrades
  cleanly. **No schema change needed for Task 5.**
