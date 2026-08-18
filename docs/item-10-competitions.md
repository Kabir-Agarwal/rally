# Item #10 — Add competitions hub — Create / Manage / In-Queue / Scheduled (SPEC Y3)

Y3 ADD: the **competitions hub**. Tournaments (item #7) and leagues (item #8) each shipped a proven
ENGINE; this is the container that ties them together and gives a competition a **lifecycle** and a
home on the hub's **four sections**:

| Section       | Holds competitions that are…                          | Status       |
|---------------|-------------------------------------------------------|--------------|
| **Create**    | being set up; not yet open for entry                  | `draft`      |
| **In-Queue**  | open for entrants; waiting to fill / get a date       | `open`       |
| **Scheduled** | field + start time locked; waiting to run             | `scheduled`  |
| **Manage**    | running or finished; the owner advances / reviews it  | `live`, `completed` |

Rally is LIVE and features land block by block (item #2), so this ships the **hub engine** — the
real, testable brain — while the competitions table + the Create/Manage form wiring land with the
batched migrations (item #19, SPEC Y5 — no session applies schema). Same sibling shape as items #7–#9:
a pure engine, preflight-gated now, wired to the DB/UI later. The hub screen lands as **dummy UI**
now (`blocks.py`: competitions `off -> dummy`), so the **Compete** tab and `/competitions` route go
live as a "Coming soon" placeholder with the engine proven behind them.

## The one file to know: `competitions.py`

A dependency-free, DB-free engine over plain competition dicts (same style as the sibling engines). A
competition names a **format** (`tournament` | `league`) and moves **forward** through the lifecycle:
`draft -> open -> scheduled -> live -> completed`.

- `normalize_status` / `status_of` — trust guard: `None`/`""`/absent → `draft` (a new competition),
  case/space tolerant (a UI value), anything else **raises**.
- `bucket_of(status)` / `hub(competitions)` — sort any list of competitions into the four sections.
  The four buckets **partition** the input: every competition lands in exactly one section, none
  dropped or duplicated — the invariant the hub screen renders from.
- `advance(comp, to)` — move one step forward, returning an **updated copy** (the caller's dict is
  untouched). Illegal jumps **fail loud**; entering `scheduled` requires a start time **and** a field
  size legal for the format (tournament 4–32, league 3–32) — no dateless or unfillable schedule.
- `start(comp)` — start a `scheduled` competition: advance it to `live` and **dispatch its entrants
  to the right sub-engine** — a first-round bracket (`tournaments.first_round`) for a tournament, a
  full round-robin schedule (`leagues.schedule`) for a league. This is the hub actually **driving
  both engines** — the thing that makes it a *competitions* hub and not a generic status board.

`FORMATS` is the tie to the two sub-engines: each format names the engine call plus that engine's own
entrant bounds — a single source of truth, no magic numbers duplicated.

## Enforcement (same mechanism as items #2–#9)

- `deploy.py` `preflight()` calls `competitions.check()` beside `tournaments.check()` /
  `leagues.check()` / `practice.check()` and the Y2 guards. `check()` proves the status trust guard +
  default, that the **four sections partition every status**, the legal lifecycle + fail-loud illegal
  jumps, the scheduling guards, and that `start()` **dispatches to the right sub-engine**. A
  regression **aborts the deploy** before a file is uploaded.
- `test_competitions.py` is the runnable check (pytest): the four sections, the partition, the
  one-step-at-a-time pure lifecycle, illegal jumps + schedule guards, and format-dispatch — all
  green, alongside the full suite.

## Also fixed

- `test_blocks.py::test_off_and_unknown_blocks_404` asserted `/leagues` 404s "still off", but item #8
  flipped leagues to `dummy` (200) and left the test stale — it was **failing on `master`**. Repointed
  it at `nearby` (genuinely still `off`) so the "off ⇒ 404" contract stays honestly tested after this
  item flips `competitions` to `dummy`.

## Scope (ponytail)

Built: the hub lifecycle/section/dispatch engine + a runnable check, wired into preflight, plus the
dummy Compete tab. **Skipped** (belongs to later blocks): the competitions table and the Create/Manage
**forms**/persistence (item #19 migrations), and reschedule/cancel transitions (not in the four the
spec names). No schema, no new dependency, no money.
