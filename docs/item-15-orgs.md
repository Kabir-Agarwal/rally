# Item #15 — Add org/club accounts (SPEC Y3)

Y3 ADD: **org/club accounts**. The item-0 study names the substance — *"org entity, roles: a club ≈ a
group + owner role"*. The existing `groups` table is a private space keyed by a code with **one scalar
`admin_id`**; an org/club **account** is a public identity with a real membership **ladder** — who
owns it, who may manage it, who merely belongs. That role model is the irreducible core, so the engine
is exactly that: an account **profile** + a **role graph** with one protected invariant.

| Half        | What it is                                                                                    |
|-------------|-----------------------------------------------------------------------------------------------|
| **profile** | `account(name, handle, kind)` is the **trust boundary**: the display name is non-empty (whitespace rejected, stored stripped, like `feed.post`), the public **@handle** is normalized (`@` dropped, lowercased) and charset/length-checked (3–30 of `a-z 0-9 _`), and the kind is a **club** or an **org**. Returns the validated profile only — the caller stamps id + created_at (no clock/id in a pure engine). |
| **roles**   | A membership is `{"org","player","role"}` with **OWNER > ADMIN > MEMBER**. The one invariant: **an account always has exactly one owner** — `found()` seeds it, `transfer()` moves it, nothing ever removes it. |

Rally is LIVE and features land block by block (item #2), so this ships the **engine** while the
`accounts` + `memberships` tables and the club profile / roster / manage controls land with the batched
migrations (item #19, SPEC Y5 — no session applies schema). Same sibling shape as items #7–#14: a pure
engine, preflight-gated now, wired to DB/UI later. The Clubs screen lands as **dummy UI** now
(`blocks.py`: orgs `off → dummy`), so the **Clubs** tab and `/orgs` route go live as a "Coming soon"
placeholder with the engine proven behind them.

## The one file to know: `orgs.py`

A DB-free engine over plain dicts (same style as the sibling engines).

- `account(name, handle, kind=CLUB)` / `normalize_handle(handle)` — build + validate the account profile.
- `found(org, owner)` — the founding membership: the creator seated as the **sole OWNER**.
- `role_of` / `is_member` / `can_manage` / `roster` / `orgs_of` — the reads: a player's role, membership,
  whether they may run the roster (rank ≥ ADMIN), the club page's members (owner-first), and the "Clubs"
  list on a player's profile (`{org: role}`).
- `add(org, actor, player, members)` — a manager (admin+) admits `player` as a **MEMBER**. Guards:
  actor must manage; no duplicate membership. New members always join at MEMBER.
- `set_role(org, actor, player, role, members)` — the **owner** grants/revokes **ADMIN** (MEMBER↔ADMIN).
  Guards: owner-only; can't set OWNER (that's `transfer`); can't touch the owner's own row; target must
  be a member.
- `remove(org, actor, player, members)` — a **self-leave**, or `actor` removing someone of **strictly
  lower** role (owner→admins/members, admin→members). The **owner is never removable** (not even by
  leaving). Returns a new members list without that row.
- `transfer(org, owner, to, members)` — the **only** way OWNER moves: old owner → ADMIN, new owner →
  OWNER, atomically, so the account is never ownerless and never two-owned.

## Why not just reuse `groups`?

`groups` has a single `admin_id` — no ladder, no co-management, no succession. An *account* is defined by
**who controls it**: multiple admins under one protected owner, promotion/demotion, and an ownership
**transfer** that can't leave the account ownerless. Without roles an "account" is indistinguishable from
a named group; the role graph is the feature, not gold-plating.

## Why "exactly one owner" (and why `add`/`set_role` can't grant OWNER)

A single protected owner is the minimal coherent account model: it makes "who can delete/transfer this
club" unambiguous and keeps the account from ever becoming ownerless. Ownership therefore moves **only**
through `transfer()`, which swaps both rows in one step — so `add` (joins as MEMBER) and `set_role`
(ADMIN↔MEMBER) deliberately refuse OWNER, and `remove` refuses the owner. `check()` asserts the invariant
holds after every operation.

## Enforcement (same mechanism as items #2–#14)

- `deploy.py` `preflight()` calls `orgs.check()` beside `feed.check()` and the rest. `check()` proves the
  profile trust guards, the role reads, the whole manage lifecycle (add / set_role / remove / transfer
  with every permission + the protected-owner invariant), and purity. A regression **aborts the deploy**
  before a file is uploaded.
- `test_orgs.py` is the runnable check (pytest): profile guards, found, add, set_role, remove, transfer,
  and the reads — green alongside the full suite (246 passed).

## Scope (ponytail)

Built: the account-profile + role-graph engine + a runnable check, wired into preflight, plus the dummy
**Clubs** tab. **Skipped** (belongs to later blocks): the `accounts`/`memberships` tables + the club
profile / roster / manage UI (item #19 migrations); **handle uniqueness** — a DB unique index, not an app
scan (a pure engine holds no registry of every handle, same as `feed` leaves id assignment to the DB);
who-may-see a club + block/report + the 16+ gate (item #16 public layer); a club **posting/competing** as
an entity — that's the feed/competitions engines already built, joined to an org id at the DB layer, no
new engine logic. No schema, no new dependency, no money.
