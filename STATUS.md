# STATUS

Owner-facing cards raised by the build sessions. `✋ WAITING-OWNER` = a decision only the owner
can make (money, or a spec clarification). Sessions never spend and never guess these.

---

## ✋ WAITING-OWNER — COST CARD: going public outgrows the free tier

Raised by item #0 (SPEC Y7). Verified with `freetier_check.py` (`python freetier_check.py`).

**What.** Rally's current friend-group traffic sits comfortably inside the free tier with huge
headroom. **Public traffic does not.** The cause is the 3-second Live poll routed through one
Vercel function; it exhausts **Vercel function invocations** and **Supabase egress** long before
database size, storage, or MAU. One continuously-open live-match tab already ≈ 1.7× the entire
monthly Vercel invocation budget and ≈ 2.8× the Supabase egress budget.

**Do the free thing first (no money, part of item 16 / Y1 prod-safe):** cut the polling firehose
— longer interval / conditional GETs / SSE / Supabase Realtime. This is required regardless and
buys large headroom (3s→30s = 10× fewer invocations).

**Two things still need an owner decision — sessions stop here:**

1. **Usage after mitigation.** Real public concurrency will still exceed the free caps on
   invocations/egress. If/when it does, the free tier *pauses the project* (no surprise bill) —
   so the app goes offline rather than charging you. Upgrading avoids the pause:
   - Vercel **Pro** — ~**$20 / seat / month** (adds overage headroom above the Hobby caps).
   - Supabase **Pro** — ~**$25 / month** (raises db to 8 GB, egress to ~250 GB, MAU to 100k).
   - Rough combined floor: **~$45 / month** to run public without pausing. *Confirm live prices
     at purchase — I did not and will not transact.*
2. **Plan terms, independent of usage.** Vercel **Hobby is personal / non-commercial only.** A
   public-facing app (especially if ever monetised) is a terms question even at low usage; that
   likely means Vercel Pro on principle, not just on volume.

**Options for the owner:**
- (a) Stay free + ship the polling mitigation, and accept "pauses at the cap / non-commercial
  terms" for a soft/limited public launch.
- (b) Approve the ~$45/mo Pro upgrades before/at public launch.
- (c) Change hosting (e.g. a fixed-price VPS from the repo `Dockerfile`) — different trade-off,
  needs its own card.

**Blocking?** No — item #0's job was to *verify and report*, which is done. This card gates the
future go-public/upgrade step, not the Y1–Y5 build.

---

## ✋ WAITING-OWNER — APPLY: batched feature-block migrations (SPEC Y5)

Raised by item #19. Verify with `python migrations/check_migrations.py`.

The Y3/Y4 feature **engines are built and preflight-gated**, but their screens stay **dummy** (SPEC
Y1) until their tables exist. SPEC Y5: **no build session applies schema** — the migrations are
staged as `migrations/block-N.sql` (`PROPOSED / NOT APPLIED`) for you to apply via the **Supabase
MCP** (`apply_migration`), in order, then each screen flips dummy → live in its own wiring item.
This is the **single planned pause** SPEC Y5 calls for — one card for the whole batch.

**Apply in order, after `2026-07-27_identity_foundation.sql`:**

| Block | Feature (item) | Adds |
|------:|----------------|------|
| block-9  | practice-vs-rated (#9)  | `matches.mode` |
| block-10 | competitions hub (#10)  | `competitions`, `competition_entrants` |
| block-11 | nearby (#11)            | `players.lat/lng/discoverable` (connections reuse `friendships`) |
| block-12 | messenger (#12)         | `messages` |
| block-13 | highlights (#13)        | `highlights`, `highlight_ratings` |
| block-14 | posts feed (#14)        | `follows`, `posts` |
| block-15 | org/club accounts (#15) | `accounts`, `memberships` |
| block-16 | public layer (#16)      | `blocks`, `reports`, `accounts.visibility`, `players.dob`/`location_permission` |
| block-20 | Y6 Tier-1 video (#20)   | `video_stats` (laptop tool's stats JSON; highlight clips reuse the `highlights` table) |

Items **#17 (skill rating)** and **#18 (form count)** need no schema — both recompute on read.

Every file is **additive + idempotent** (`IF NOT EXISTS`): existing rows/columns are untouched, so
prod never breaks, and a re-apply is safe. **Sessions never run these.**

**Blocking?** No — item #19's job was to *adopt the convention and stage the batch*, which is done.
This card gates the owner's apply step, not the build.

---

## ✋ WAITING-OWNER — CLARIFY: what is "Playeri"?

Raised by item #0 (SPEC Y7 says "re-study current **Playeri**").

Two web passes (2026-08-18) found no specific product named "Playeri". I did **not** invent one.
The steal-worthy feature study (`docs/item-0-study.md` §A) is instead grounded in the verifiable
racquet-app peer set (PairUp, Playtomic, UTR, RacketPal, Liga.Tennis) that Y3 was clearly modelled
on, and each feature is mapped to a queue item.

**Ask:** if "Playeri" is a specific app (URL / store listing / screenshots), point me at it and
I'll diff it against the study and pull anything the peer set missed. Otherwise the peer-grounded
study stands as the item #0 deliverable.
