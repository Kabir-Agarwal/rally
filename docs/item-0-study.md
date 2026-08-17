# Item #0 — Playeri re-study, reuse-audit, free-tier headroom (SPEC Y7)

Foundational research item. Three outputs: (A) steal-worthy features, (B) reuse-audit that
tells every later item what already exists, (C) free-tier verdict. (C) is the runnable
`freetier_check.py`; its cost card is in `STATUS.md`.

---

## A. Steal-worthy features

**Naming flag (WAITING-OWNER, not a blocker).** "Playeri" resolves to no specific product from
here — two web passes (2026-08-18) returned only the racquet-app peer set below, none named
"Playeri". Per the runner's rule I did not invent a "Playeri" spec sheet. Instead I sourced
steal-worthy features from the **verifiable** peers this SPEC's Y3 was clearly modelled on and
mapped each to a queue item. If "Playeri" is a specific app you have in mind, point me at it and
I'll diff it against this list. See `STATUS.md`.

Peers studied: **PairUp** (1–10 PUR rating + Rookie/Club/Advanced/Elite tiers), **Playtomic**
(1M+ community, advanced match/set stats, level-based matchmaking, booking), **UTR** (rating
refreshes every 24h, trusted/verified), **RacketPal** (find local partners by sport & level),
**Liga.Tennis** (post/share content, follow players, improve via regular competitive games),
**Tennis Padel Score Keeper** (customisable player card — photo, skill level, playing style).

| # | Steal-worthy feature | Seen in | Lands in queue item |
|---|----------------------|---------|---------------------|
| 1 | **Named skill tiers** banded over the raw number (Rookie→Elite) — motivating, readable | PairUp | 17 (Elo FIFA card) — cheap add over `ratings.py` |
| 2 | **Level-based matchmaking** — suggest opponents near your rating within range | Playtomic, RacketPal | 11 (nearby players) |
| 3 | **Customisable player card** — photo + playing-style tags on the FIFA card | Score Keeper, Playtomic | 17 |
| 4 | **Advanced match/set stats** surfaced per match (serve hold %, break %, margins) | Playtomic | 17/18 — Rally already computes these on the player page |
| 5 | **Follow players + activity feed** of their matches/posts | Liga.Tennis | 14 (posts feed) |
| 6 | **Regular competitive formats** (ladders/leagues) as the improvement loop | Liga.Tennis, Playtomic | 8 (leagues), 7 (tournaments) |
| 7 | **Rating credibility signals** — provisional vs settled, "verified result" | UTR | 17 + reuse the approval state machine (already verifies results) |
| 8 | **Content/highlights sharing with reputation** | Playtomic community | 13 (highlights, stars, laurels) |

**Protect — Rally already beats the peers here; do NOT rebuild these when adding the above:**
matches-are-the-only-truth (ratings recompute on read, always fresh vs UTR's 24h batch);
per-group privacy by URL-capability code; **doubles pair-chemistry ELO** and **Triple-Threat**
mode (no peer has these); fully inline, no-popup UX.

---

## B. Reuse-audit — what each later item reuses instead of rebuilding

Rally is small and dense; most Y3/Y4 items are **views over engines that already exist**. Reuse
column = what to wire up; New column = the genuinely new surface.

| Queue item | Reuse (already in repo) | New |
|-----------|--------------------------|-----|
| 3 Keep theme | `static/style.css` tokens | — (don't regress; `docs/drift-inventory.md` tracks mockup alignment) |
| 4 Keep doubles chemistry | `pair_ratings` in `ratings.py`, `.chemrow` UI | — |
| 5 Keep delete-past-matches | delete-with-approval flow in `logic.py` | — |
| 6 Keep earned-from-0 stats | player-page stats, last-5 form | — |
| 7 Tournaments | match lifecycle + approval + rating-on-finish (`logic.py`), card UI | bracket gen, BYEs, live bracket view; `tournaments`/`tournament_matches` tables |
| 8 Leagues (round-robin) | same match engine; standings from `ratings.py` | schedule generator, standings view |
| 9 Practice-vs-rated split | `match.kind` + `status='counted'` gating already in `ratings.py` | a `rated` flag + toggle |
| 10 Competitions hub | tab shell + card grid; group model | Create/Manage/In-Queue/Scheduled views |
| 11 Nearby players 50km | **Connect == existing `/api/friend/request`**; player card | geolocation, 50km query, permission handling |
| 12 Messenger + basic AI | auth + group membership | messages table, thread UI, *basic* helper (advanced AI is OUT) |
| 13 Highlights | reputation/form count (item 18) drives stars | landscape video upload, laurels; ties to Y6 |
| 14 Posts feed + followed matches | friend/follow graph, public-match visibility, card components | posts table, feed view |
| 15 Org/club accounts | **admin console patterns** (`app.py` `/admin`, `admin_log`); a club ≈ a group + owner role | org entity, roles |
| 16 Public layer | `is_public` toggle, read-only public banner (already live) | privacy controls, block/report (extend `admin_log`), location-permission, 16+ gate |
| 17 Elo skill rating on FIFA card | **`ratings.py` already IS the skill number** | just surface it as a card + tiers (feature #1/#3 above) |
| 18 Activity/reputation form count | match history + last-5 form already rendered | a separate counter (Y4: two numbers, separate) |
| 19 Batched migrations | **`migrations/` pattern already exists** (`2026-07-27_identity_foundation.sql` + `backfill_identity.py`) | one `block-N.sql` per feature block; owner applies via Supabase MCP |
| 20–21 Y6 video | — | new, laptop-only, LAST (owner ruling) |

**Cross-cutting reuse (applies to every new endpoint):** `test_query_budget.py` counts DB
round-trips and fails a regression. Every Y3 endpoint must keep its round-trip count flat in row
count — this is the same lever the free-tier finding below turns on. Reuse this test as the
gate, don't invent a new perf story per feature.

---

## C. Free-tier headroom — verdict

Run `python freetier_check.py`. Summary: **free tier is comfortable at friend-group scale and
breaks at public scale.** The break is caused by the **3-second Live poll**
(`/api/live` + `/api/match/<id>`, README "Screens"), routed through the single catch-all
function (`api/index.py`). It hits **Vercel function invocations** and **Supabase egress**
first — not database size, storage, or MAU.

- One continuously-open live-match tab ≈ **1.7M invocations/mo** > the 1M Vercel cap, and
  ~**14 GB egress** > the 5 GB Supabase cap. A single dedicated watcher ≈ the whole free tier.
- Database is a non-issue: 500 MB holds ~500k matches (matches are the only stored truth,
  rebuilt on read). MAU cap (50k) is far off.
- **Free mitigation that must land before public (part of item 16 / Y1 prod-safe):** cut the
  polling firehose — longer interval / conditional GETs / SSE / Supabase Realtime. Model shows
  3s→30s alone pulls one dedicated tab back under the invocation cap (10× fewer invocations).
- **Two triggers still force an owner money decision — see the `STATUS.md` cost card:** (1) even
  after mitigation, real public concurrency will exceed free invocations/egress; (2) Vercel
  Hobby is **personal/non-commercial only**, so a public app is a plan-terms question
  independent of usage.

Sources (2026-08-18): Vercel Hobby & Supabase Free tier limits per current vendor-pricing
writeups; peer features per the app-store/Play-store listings linked during research.
