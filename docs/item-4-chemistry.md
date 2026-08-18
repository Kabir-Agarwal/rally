# Item #4 — Keep doubles chemistry (SPEC Y2)

Y2 KEEP: **doubles chemistry**. Rally is LIVE and Y3 features land block by block (item #2); several
of the planned ones — tournaments, leagues, the practice-vs-rated split — touch the rating pipeline
in `ratings.py`. "Keep doubles chemistry" makes the pair rating a **contract**, not a promise, so a
later block can't quietly stop rating duos or move the goalposts.

## What "doubles chemistry" is

The per-duo **pair rating** (`ratings.py` `_apply_pair` / `state["pairs"]`, `state["pairs_n"]`): a
pair is rated as a *unit*, distinct from the two players' individual doubles ratings. It is
order-independent (`canon` keys `(a,b)` and `(b,a)` the same), zero-sum between the two duos, and
**provisional** under `PAIR_PROVISIONAL` finished pair-matches. It surfaces in the app via the
doubles win-probability (uses the pair rating once both duos are established — `app.py`
`win_prob_for`), `/api/meta`'s `pairs` + `pair_provisional`, and the player card's chemistry rows
(`player_payload`, `renderChem` / `.chembox` in `log.js`).

## The one file to know: `chemistry.py`

`chemistry.check()` exercises the **real** `ratings` engine and fails loud if the contract regressed:

1. `new_state()` still carries the pair slots (`pairs` / `pairs_n`).
2. One finished doubles match rates the duo as a unit — a pair slot appears, counted once,
   winner-duo up / loser-duo down, zero-sum.
3. Order-independent: a reversed line-up lands in the *same* pair slots, not new ones.
4. The provisional gate is frozen at **3** (`chemistry.PROVISIONAL`), counted one per pair-match.
5. Chemistry is doubles-only — a singles match never leaks a pair rating.

`chemistry.PROVISIONAL` is the frozen copy of `ratings.PAIR_PROVISIONAL`. To move the gate on
purpose, edit it in **both** places — the double edit is the point: the gate only moves when someone
means it to, in one reviewable spot, never as a side effect buried in a feature diff.

## Enforcement (same mechanism as items #2 and #3)

- `deploy.py` `preflight()` calls `chemistry.check()` right beside `blocks.validate()` and
  `theme.check()`. A build that regressed the pair contract **aborts the deploy** before any file is
  uploaded.
- `test_chemistry.py` is the runnable check: the live engine satisfies the contract, and the two
  regressions that matter — a block that stops rating duos (`_apply_pair` no-op), or one that moves
  the provisional gate — are caught.

Scope: the guard locks the engine contract — `ratings.py` is the single source of truth for the
numbers. The `/api/meta` keys that carry chemistry to the UI (`pairs`, `pair_provisional`) are
already guarded by `test_ui_support.py::test_meta_shape_zero_based`.
