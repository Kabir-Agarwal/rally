# Item #3 — Keep the theme (SPEC Y2)

Y2 KEEP: **theme**. Rally is LIVE and Y3 features land block by block (item #2); nearly every one
edits `static/style.css`. "Keep the theme" makes the approved CLAY palette a lock, not a promise —
so a later feature can't quietly recolour or drop it.

## The one file to know: `theme.py`

`theme.TOKENS` is the frozen palette — the 13 `:root` design tokens from `static/style.css`
(`--clay`, `--sand`, `--yellow`, `--live`, `--radius`, …), at their approved values. It is an
independent copy of the truth: the CSS must conform to it, not the other way round.

`theme.check()` reads `static/style.css`, extracts the `:root` tokens, and aborts if the live
palette drifts from the lock — a **dropped** token, a **changed** value, or a **new** `:root`
token that isn't in the lock. Colours compare case-insensitively, so reformatting `#A94E2F` →
`#a94e2f` is fine; changing the colour is not.

## Changing the palette on purpose

The lock isn't a freeze-forever — it's a speed bump. To change a theme colour: edit the value in
BOTH `static/style.css` and `theme.TOKENS`. The double edit is the point — the palette only moves
when someone means it to, in one reviewable place, never as a side effect buried in a feature diff.

## Enforcement (same mechanism as item #2)

- `deploy.py` `preflight()` calls `theme.check()` right beside `blocks.validate()`. A build that
  regressed the palette **aborts the deploy** before any file is uploaded.
- `test_theme.py` is the runnable check: the live CSS matches the lock, the lock covers the whole
  `:root` palette, and a recoloured / dropped token is caught.

Scope: the lock guards the `:root` design tokens (the theme). It does not police one-off literal
hex values scattered in component rules — those are out of scope for Y2 and tracked, where they
matter, by `docs/drift-inventory.md` ("Palette/tokens already match").
