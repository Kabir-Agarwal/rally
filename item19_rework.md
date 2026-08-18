# item 19 rework — Adopt batched migrations — one migrations/block-N.sql per feature-block, owner applies via Supabase MCP (SPEC Y5)

cycle: 1

## checker findings, verbatim and entire

Batch is incomplete against Y5 "one block-N.sql per feature-block": item #16 (public layer) explicitly defers its persistence to item #19's batch (public.py:36-40 — tables `blocks` and `reports`, columns `accounts.visibility` and `players.dob`/`players.location_permission`), yet item #19 stages none of them: no block-16.sql exists, block-15's `accounts` has no `visibility` column, no block adds `players.dob`, and grep of every migrations/*.sql finds no `blocks`/`reports`/`dob`/`visibility`/`location_permission`; STATUS card table, README block table, and README "no schema needed" note all silently omit #16, and no later queue item exists to home it.
