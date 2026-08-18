# Item #12 — Add messenger + basic AI helper (SPEC Y3)

Y3 ADD: **messenger + basic AI helper**. Nearby players (item #11) let you **Connect**; this is what
you do once connected — **message** each other — plus the **basic AI helper** that lives in the
messenger. Two pure halves:

| Half           | What it is                                                                 |
|----------------|----------------------------------------------------------------------------|
| **messenger**  | Direct messages between two players. A conversation is one unordered pair, keyed the **same way a connection is** (`nearby.pair_key`, the friendships shape) — so "message" follows naturally from "Connect". Threads read oldest-first; an **inbox** lists conversations (who / last message / unread, newest first); an unread/read model drives the badge and read receipts. |
| **AI helper**  | A **basic** assistant: smart quick-replies. It reads the other player's last message into one small **intent** (invite / time / question / greeting / thanks / general) and offers 2–3 ready-to-tap replies — the "smart reply" bar. A **keyword heuristic, not an LLM**. |

Rally is LIVE and features land block by block (item #2), so this ships the **engine** — the real,
testable brain — while the messages table + the thread/inbox screens + the smart-reply bar land with
the batched migrations (item #19, SPEC Y5 — no session applies schema). Same sibling shape as items
#7–#11: a pure engine, preflight-gated now, wired to the DB/UI later. The Messages screen lands as
**dummy UI** now (`blocks.py`: messages `off -> dummy`), so the **Messages** tab and `/messages` route
go live as a "Coming soon" placeholder with the engine proven behind them.

## The one file to know: `messenger.py`

A DB-free engine over plain message dicts (same style as the sibling engines). A message is
`{"pair", "sender", "body", "at", "read"}`; `pair = nearby.pair_key(a, b)` (a<b canonical, exactly a
connection's key), `at` is any sortable timestamp the **caller** stamps (a pure engine has no clock),
`read` is whether the **recipient** has seen it.

- `compose(me, them, body, at)` — build a message (caller persists). **Trust-boundary guards**:
  non-empty body (arrives from a user — whitespace-only rejected), can't message yourself, needs a
  timestamp to order by. Body is stored stripped; the pair is canonical regardless of arg order.
- `thread(messages, me, them)` — the conversation, **oldest first**, only that pair's messages (other
  conversations ignored), stable on equal timestamps.
- `unread_count` / `mark_read` — the read model. Count/clear only messages **addressed to me** and
  unread; scoped to one conversation or **global** (the badge). `mark_read` is **pure** — returns a new
  list, the caller's messages untouched.
- `inbox(messages, me)` — the conversation-list screen: one row per person (`with`, `last`, `unread`),
  **newest conversation first**.
- `classify(body)` — the tiny intent "model": keyword match in priority order (thanks and a concrete
  time win first — they're usually the point — then invite, greeting, a bare question, else general).
  Whole-word matching, so "hey" misses "they" and "ty" misses "party".
- `suggest_replies(messages, me, them)` — the **basic AI helper**: if the other player spoke last,
  classify their message and suggest replies to it; if it's my turn (or the thread is empty), suggest
  an opener. Always a fresh list.

## Why the AI helper is rule-based, not an LLM

Deliberate, and doubly required: SPEC **OUT** keeps *"advanced messenger AI"* for v2, and the **money
wall** forbids a paid model. A keyword smart-reply is the classic *basic* messenger AI — deterministic,
free, and fully testable. `messenger.py` marks the ceiling with a `ponytail:` comment: the upgrade path
(a real intent model / LLM) is exactly the v2 work the spec defers.

## Enforcement (same mechanism as items #2–#11)

- `deploy.py` `preflight()` calls `messenger.check()` beside `nearby.check()` / `competitions.check()`
  and the rest. `check()` proves the compose trust guards, chronological/isolated threads, the
  unread+read model (scoped and pure), the inbox conversation-list, `classify` across every intent
  incl. priority collisions, and `suggest_replies`. A regression **aborts the deploy** before a file
  is uploaded.
- `test_messenger.py` is the runnable check (pytest): compose guards, threads, unread/mark_read,
  inbox, the intent table, and the smart-reply behaviour — green alongside the full 209-test suite.

## Scope (ponytail)

Built: the DM/inbox/unread engine + the basic-AI smart-reply helper + a runnable check, wired into
preflight, plus the dummy **Messages** tab. **Skipped** (belongs to later blocks): the messages table
and the thread/inbox screens + smart-reply bar (item #19 migrations); DM gating to accepted
connections + block/report + 16+ gate (item #16 public layer); anything LLM-shaped ("advanced
messenger AI" = v2/OUT). No schema, no new dependency, no money.
