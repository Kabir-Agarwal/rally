# Item #21 — Y6 Stage-0 gate: Tier 2 waits on the owner's real clip (SPEC Y6)

SPEC Y6: *"Stage-0 accuracy test runs … before any deeper vision work."* Owner ruling (14 Aug 2026):
*"Tier 2 only after the owner's real Stage-0 clip validates."*

Item #20 shipped the **Tier-1** engine on a deliberately simple **frame-diff motion signal**. That
signal's accuracy on real footage is **unproven** — and it is exactly what must be proven before anyone
builds ball/player detection (**Tier 2**) on top of it. This item is that **gate**. It does **not** build
Tier 2 (owner: not yet) — it makes Tier 2 **impossible to start** until a real clip clears the bar.

## The one file to know: `stage0.py`

Pure stdlib (scoring + gate + `check()`), so it ships to Vercel dormant and runs in `deploy.py`
preflight beside the sibling engines. Only `validate()` touches vision, and only on the laptop.

- `score(labels, stats)` — scores the Tier-1 tool's detected rallies (`stats` from `video.analyze`)
  against the owner's hand labels by **temporal IoU**, greedy-matched → `recall`, `precision`,
  `mean_iou`, `count_error`.
- `passed(metrics, thresholds)` — PASS/FAIL against the accuracy bar, with the reasons it failed.
- `require_tier2_unlocked()` — **the gate.** The required **first line of every future Tier 2
  entrypoint.** Raises `Tier2Locked` unless a recorded Stage-0 verdict's own metrics still clear the
  thresholds. Fail-closed (see below).
- `validate(clip, labels)` — **laptop-only.** Runs `video.process_video` on the owner's real clip,
  scores it, and records `stage0_verdict.json`. The **only** path that writes the verdict.

## The accuracy bar (`THRESHOLDS`, owner-tunable)

| Metric | Min | Meaning |
|--------|----:|---------|
| `recall` | 0.80 | the tool finds ≥80% of the real rallies |
| `precision` | 0.80 | ≤20% of its detections are spurious |
| `mean_iou` | 0.50 | matched spans overlap the real ones ≥ half on average |

A labeled rally is *found* when some detection overlaps it with IoU ≥ `0.30`.

## Fail-closed — the gate can only be opened by a real pass

`require_tier2_unlocked()` **recomputes** pass/fail from the recorded metrics — it never trusts the
verdict's `"result"` string — and the recorded thresholds may only be made **stricter**, never looser,
than the built-ins. So **missing**, **malformed**, **FAIL**, a bare `{"result":"PASS"}`, or a verdict
with **hand-lowered thresholds** all leave Tier 2 **LOCKED**. `stage0_verdict.json` is **git-ignored**,
so a pass lives only on the machine that actually ran a real clip — it can't be committed to unlock
everyone.

## How the owner runs Stage-0 (see the STATUS card)

1. Film a short **real** clip per the capture guidance (tripod, landscape, whole court) — a couple of
   minutes with a handful of rallies is enough.
2. Watch it and hand-label each rally's start/end. Seconds or `m:ss` both parse:
   ```json
   { "clip": "practice.mp4",
     "rallies": [ {"start_s": "0:04", "end_s": "0:11"},
                  {"start_s": "0:19", "end_s": "0:28"} ] }
   ```
3. `pip install -r requirements-video.txt` then `python stage0.py practice.mp4 labels.json`.
4. **PASS** → `stage0_verdict.json` records it and Tier 2 unlocks. **FAIL** → the frame-diff signal
   isn't accurate enough yet; Tier 2 needs a better signal (real ball/player detection) *before* it
   pays off — which is precisely what Stage-0 exists to tell you.

## Enforcement (same mechanism as items #2–#20)

- `deploy.py preflight()` calls `stage0.check()` beside `video.check()`. `check()` proves scoring
  (perfect match → PASS, missing/off-target → FAIL, `m:ss` parsing) **and** that the gate fails closed
  — all on **in-memory** verdicts, never the real file, so preflight can never unlock Tier 2.
- `test_stage0.py` is the runnable pytest: the same scoring cases plus the gate directions (locked by
  default, raises, ignores hand-lowered thresholds, opens on a genuine pass).

## Scope (ponytail)

**Built:** the Stage-0 scorer (temporal-IoU recall/precision/mean-IoU), the PASS/FAIL bar, the
fail-closed `require_tier2_unlocked()` gate, the laptop-only `validate()` that records the verdict, a
runnable check wired into preflight, and the WAITING-OWNER card. **Skipped** (by ruling): **Tier 2
itself** — that is what the gate is protecting; it starts only after the owner's real clip passes. No
schema (the verdict is a local file, git-ignored), no web dependency, no money (reuses the item-20
free-libraries laptop path).
