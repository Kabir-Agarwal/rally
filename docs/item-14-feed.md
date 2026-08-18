# Item #14 — Add posts feed + followed players' matches (SPEC Y3)

Y3 ADD: **posts feed + followed players' matches**. Three pure halves:

| Half             | What it is                                                                             |
|------------------|----------------------------------------------------------------------------------------|
| **follow**       | You **follow** a player. Following is **directed and asymmetric** — I follow you does not mean you follow me. So a follow is keyed by the **ordered** pair `(follower, followee)`, deliberately **not** `nearby.pair_key`'s canonical `a<b` (the friendships shape a connection / a DM uses). `A→B` and `B→A` are two distinct edges that can **both** exist (a mutual follow) — something a canonical pair could never store. |
| **posts**        | A player writes a **post** (text). `post()` is the **trust boundary** (the body arrives from a user) — it refuses an empty/whitespace body and demands a timestamp to order by, exactly like `messenger.compose`. A post is `{"author","body","at"}`. |
| **the feed**     | The one call the screen makes: merge into a single **newest-first** timeline (a) the posts and (b) the **matches** of everyone I follow — and my own — each row **tagged with its kind** so the UI renders a post card vs a match result. The two data sources joined the way `nearby.discover()` / `competitions.hub()` tie their engines together. |

Rally is LIVE and features land block by block (item #2), so this ships the **engine** — the real,
testable brain — while the `follows` + `posts` tables, the compose box, the follow button and the
merged timeline land with the batched migrations (item #19, SPEC Y5 — no session applies schema). Same
sibling shape as items #7–#13: a pure engine, preflight-gated now, wired to the DB/UI later. The Feed
screen lands as **dummy UI** now (`blocks.py`: feed `off → dummy`), so the **Feed** tab and `/feed`
route go live as a "Coming soon" placeholder with the engine proven behind them.

## The one file to know: `feed.py`

A DB-free engine over plain dicts (same style as the sibling engines).

- `follow(follower, followee, edges)` — build one **directed** follow edge (caller persists). **Guards**:
  no self-follow, no same-direction duplicate. The **reverse** edge is a different follow and may coexist.
- `is_following(me, them, edges)` — the bit the **Follow / Following** button reads (directional).
- `following(me, edges)` / `followers(me, edges)` — the two directions as sets: who I follow (fills my
  feed) and who follows me (the profile count).
- `post(author, body, at)` — build a post; **trust guards**: non-empty body (stripped), a timestamp to
  order by.
- `players_of(match)` — a match's participants (`side1 + side2`, the app's existing match shape); the
  feed surfaces a match when a followed player (or me) is one of them.
- `feed(me, posts, matches, edges, limit=None)` — the merged timeline. **Audience = `following(me)` ∪
  `{me}`.** A post is in when its author is in the audience; a match is in when any participant is —
  that's **followed players' matches**. A live match with no `at` is **skipped** (can't be placed on
  the timeline). Rows are **copies** tagged with `kind`, **newest first**, capped to `limit`.

## Why following is a *directed* edge (not the friendships pair)

Connect (`nearby`) and DMs (`messenger`) are **symmetric** — one unordered `pair_key(a, b)` row. Following
is **not**: it's a one-way subscription, so the edge must remember **who followed whom**, and a mutual
follow is genuinely two rows. Reusing the canonical pair here would collapse `A→B` and `B→A` into one and
make "does A follow B?" unanswerable. The `check()` proves the mutual-follow case explicitly.

## Why your own activity is in your feed

`feed()`'s audience is *the people I follow, **and me***, so a brand-new user with zero follows still
sees their own posts and matches (every social feed shows your own activity). The **new capability the
spec names** is *followed players' matches* — surfacing the match rows of the people you follow beside
their posts.

## Enforcement (same mechanism as items #2–#13)

- `deploy.py` `preflight()` calls `feed.check()` beside `highlights.check()` / `messenger.check()` and
  the rest. `check()` proves the directed follow graph (incl. the mutual follow), the post trust guards,
  participant extraction, and the merged timeline (audience filter, match surfacing, newest-first order,
  tagging, limit, purity). A regression **aborts the deploy** before a file is uploaded.
- `test_feed.py` is the runnable check (pytest): the follow graph, the post guards, and the merged feed
  — green alongside the full suite.

## Scope (ponytail)

Built: the follow-graph + posts + merged-timeline engine + a runnable check, wired into preflight, plus
the dummy **Feed** tab. **Skipped** (belongs to later blocks): the `follows`/`posts` tables + the compose
box / follow button / rendered timeline (item #19 migrations); block/report + private accounts + 16+ gate
(item #16 public layer); **unfollow** — removing a follow edge is a plain `DELETE` with no engine logic,
so the caller/DB owns it (no function, same as `nearby` has no "disconnect"). No schema, no new
dependency, no money.
