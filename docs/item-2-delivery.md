# Item #2 — Prod-safe, block-by-block delivery (SPEC Y1)

Rally is LIVE. Y1: **prod never breaks; features land block by block; new screens land as dummy
UI first.** This item makes that a mechanism, not a promise.

## The one file to know: `blocks.py`

Every feature-block has exactly one state:

| state | in nav? | `/<id>` | meaning |
|-------|---------|---------|---------|
| `off`   | no  | 404 | declared but invisible — the default for planned work |
| `dummy` | yes | shell + "Coming soon" panel | placeholder screen, no real logic yet |
| `live`  | yes | its own route | fully wired and shipped |

The five shipped tabs are `live`. The planned Y3 screens are pre-declared `off`.

## How a later item lands its screen

1. Flip its block `off -> dummy` in `blocks.py`. Ship. → the tab appears as a "Coming soon"
   placeholder for everyone. Nothing else changes; prod can't break because there's no new logic.
2. Build the real tab (server routes + an `initX` in `app.js` `TAB_INIT` + skeleton) behind that
   same id. When it works, flip `dummy -> live`. The dummy nav entry and placeholder drop out
   automatically (they only render for `dummy` blocks).

A half-built block is only ever `dummy` — a harmless placeholder — until its item is done, so
every intermediate deploy is safe.

## Enforcement

- `deploy.py` runs `preflight()` before uploading: it imports the app (boot check —
  `db.init_db` fails loud if unmigrated) and `blocks.validate()`. A bad registry or a build that
  can't construct **aborts the deploy** before any file is uploaded.
- `blocks.validate()` refuses duplicate ids, unknown states, and any shipped tab knocked off
  `live`.
- `test_blocks.py` is the runnable check: registry integrity, the shipped tabs still serve, a
  `dummy` block renders + injects, and `off`/unknown blocks 404.

Wiring: `blocks.dummy_blocks()` → `shell.html` (nav buttons + `window.DUMMY_BLOCKS`) → `app.js`
registers each as a routable tab with a "Coming soon" skeleton and no init. Empty in prod today,
so the whole path is a no-op until the first block is flipped to `dummy`.
