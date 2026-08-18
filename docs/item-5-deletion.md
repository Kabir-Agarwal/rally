# Item #5 — Keep delete-past-matches (SPEC Y2)

Y2 KEEP: **delete-past-matches**. Rally is LIVE and Y3 features land block by block (item #2); several
of the planned ones — tournaments, leagues, the practice-vs-rated split — touch the match lifecycle
and the rating pipeline. "Keep delete-past-matches" makes the soft, reversible delete a **contract**,
not a promise, so a later block can't quietly turn it into a hard purge or stop rolling back a deleted
match's rating.

## What "delete-past-matches" is

Deleting a match (`logic.delete_match`, exposed by `POST /api/match/{id}/delete` for a signed-in
player and `POST /admin/api/match/{id}/delete` for godmode) is a **soft delete**: `db.set_status`
stamps `status='deleted'` and **preserves the row**. Because the rating rebuild reads only
`status='counted'` (`db._rating_match_dicts`), a deleted *past* match's contribution vanishes on the
next read — deleting a match you already played rolls its rating effect back. And a deleted match
drops out of the app: it's excluded from counts (`status<>'deleted'`) and never appears in the
visible-history allow-list (`('counted','pending_approval','disputed')`, `app.py::api_history`).

## The one file to know: `deletion.py`

`deletion.check()` exercises the **real** `logic` + `db` + `ratings` engine end-to-end on an
in-memory DB (score a singles match, both approve → counted, then delete it) and fails loud if the
contract regressed:

1. **Soft**: the row is preserved and stamped `'deleted'` — never physically removed.
2. **Audit**: the tombstone keeps its children — the match's sets survive (a hard delete / cascade
   would wipe them).
3. **Rollback**: the deleted counted match no longer counts toward ratings — the winner drops back to
   the `ratings.START` baseline.
4. **Hidden**: the `status<>'deleted'` count drops to zero — deleted matches are excluded from counts.
5. **Guard**: deleting a match that isn't there raises `ValueError` (the route relies on it → 400).
6. **Schema**: `'deleted'` stays a permitted match status in `db.SCHEMA` — drop it from the enum and
   soft delete blows up at the DB layer.

## Enforcement (same mechanism as items #2, #3 and #4)

- `deploy.py` `preflight()` calls `deletion.check()` right beside `blocks.validate()`,
  `theme.check()` and `chemistry.check()`. A build that regressed the soft-delete contract **aborts
  the deploy** before any file is uploaded.
- `test_deletion.py` is the runnable check: the live engine satisfies the contract, and the two
  regressions that matter — a block that hard-purges the row instead of tombstoning it, or one that
  makes delete a no-op so a deleted past match still counts — are caught.

Scope: the guard locks the engine contract — `logic.delete_match` + the `status='counted'` rating
predicate are the single source of truth for delete semantics. The existing behaviour tests
(`test_tennis.py::test_delete_excludes_from_ratings` / `test_delete_live_immediate`,
`test_admin.py::test_godmode_match_delete`) still cover the routes; this freezes the contract they
assume.
