# migrations — batched, owner-applied (SPEC Y5)

**No build session ever applies schema.** Sessions *write* migrations here; the **owner's chat-Claude
applies** them via the Supabase MCP (`apply_migration`), deliberately, after review.

## Convention

- **One file per feature-block:** `block-<N>.sql`, where `N` is the queue item that introduces it.
- Every file is **`PROPOSED / NOT APPLIED`** and carries the standard header — including the literal
  markers `PROPOSED / NOT APPLIED` and `No session applies schema`, which the convention check
  enforces so nothing can masquerade as auto-runnable.
- **Additive + idempotent** (`IF NOT EXISTS`): a re-apply is safe and existing rows/columns are
  untouched, so **prod never breaks** (SPEC Y1).
- The app **never self-migrates**: `db.init_db` *verifies* the live Postgres schema (`require_schema`)
  and refuses to boot if unmigrated — it never creates or patches columns.

## Flow (SPEC Y5)

```
write block-N.sql  →  ONE planned ✋ in STATUS.md  →  owner applies each via Supabase MCP  →  continue
```

## Blocks

| Block | Feature (item) | SPEC | Adds |
|------:|----------------|:----:|------|
| — | identity foundation | — | `2026-07-27_identity_foundation.sql` (pre-convention base; owner-gated) |
| 9  | practice-vs-rated (#9)  | Y3 | `matches.mode` |
| 10 | competitions hub (#10)  | Y3 | `competitions`, `competition_entrants` |
| 11 | nearby (#11)            | Y3 | `players.lat/lng/discoverable` (connections reuse `friendships`) |
| 12 | messenger (#12)         | Y3 | `messages` |
| 13 | highlights (#13)        | Y3 | `highlights`, `highlight_ratings` |
| 14 | posts feed (#14)        | Y3 | `follows`, `posts` |
| 15 | org/club accounts (#15) | Y3 | `accounts`, `memberships` |

**No schema needed:** #17 skill rating and #18 form count both **recompute on read** (from matches +
laurels) — no table, nothing to apply. Laurels themselves derive from `highlight_ratings` (block 13).

Each block's screen stays **dummy UI** (SPEC Y1) until its block is applied, then flips dummy → live
in its own wiring item — so a partly-built feature never touches production.

## Check

```
python migrations/check_migrations.py
```

Validates naming, the mandatory headers, that each file holds real DDL, and the *no-session-applies*
invariant in `db.init_db`. Wired into `deploy.py` preflight beside the engine `check()`s.
