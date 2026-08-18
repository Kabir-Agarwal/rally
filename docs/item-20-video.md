# Item #20 — Y6 Tier 1 video tool (SPEC Y6)

SPEC Y6 + the owner ruling (14 Aug 2026): **build Y6 fresh from free open-source vision libraries,
laptop-only, LAST.** Only the **stats JSON + highlight clips** upload — never the raw match video. The
**Tier 1** set is exactly: **rally segmentation, rally counts/lengths, highlight reel, movement
heatmaps.** Tier 2 (deeper vision) is **gated on the owner's real Stage-0 clip** — that is item #21,
not this one.

This ships the whole Tier-1 tool, split on the dependency line — the same split `highlights.py` already
names ("Decoding the pixels … is the Y6 laptop-only vision tool's job"):

| Layer | What it is | Deps |
|-------|------------|------|
| **Pure engine** (`video.py`, top half) | The brain. Every Tier-1 number is pure math over **one motion signal + a motion centroid per sampled frame** — no ML model, no ball tracker (that accuracy question *is* Stage-0/Tier 2). Runs in `deploy.py` preflight and ships to Vercel as a dormant pure module, exactly like the sibling engines. | **none** (stdlib) |
| **Laptop adapter** (`video.py`, bottom half) | `process_video(path)` — opencv frame-differencing turns real footage into the signal the engine consumes, writes `stats.json`, and cuts the reel clips (ffmpeg stream-copy if present). **Lazy-imports** cv2/ffmpeg so the web app / preflight never pull them. | `requirements-video.txt` (opencv, numpy) + optional ffmpeg |

## Why the split (and why opencv is not in `requirements.txt`)

The web app deploys to the Vercel **free tier** (see the STATUS cost card). Putting opencv/numpy/torch
in `requirements.txt` would bloat or break that bundle — and the app never runs the vision pipeline
anyway (SPEC Y6: **laptop-only processing**). So the heavy deps live in a **separate**
`requirements-video.txt`, and `video.py` imports them **only inside** `extract_signal`/`process_video`.
Importing `video` (as preflight does) touches no vision dep; it stays a pure, testable module.

## The one file to know: `video.py`

A DB-free engine over plain lists/dicts, JSON-serializable throughout (the payload **is** an upload).

- `segment_rallies(motion, fps, …)` — **rally segmentation.** A frame is *active* when its motion clears
  an **auto threshold** (a fraction of *this clip's own* rest→peak range, so it adapts to any
  camera/exposure). A rally is a run of active frames, with two robustness rules: brief dips up to
  `max_gap_s` (a ball crossing, a wind-up) are **bridged**, and runs under `min_rally_s` are **dropped**.
  → `[{"index","start_s","end_s","duration_s","frames"}]`.
- `analyze(motion, positions, fps, …)` — the **one call the laptop adapter makes**: ties the four halves
  into the **"max stats"** JSON. `rallies` (count + per-rally spans + **shot estimate**), `lengths`
  (total play, active ratio, longest/shortest/avg/median, total & per-rally shots), `highlight_reel`,
  `heatmap`, and `guidance`.
- `highlight_reel(rallies, video_duration_s, …)` — **highlight reel.** The `top_n` **longest** rallies
  (Tier-1 proxy for the best points), each padded and **clamped inside the video**, in play order. The
  adapter cuts the mp4s from these spans — those clips are what upload.
- `heatmap(positions, rows, cols)` — **movement heatmap.** Bin the rally-time motion **centroids** into a
  court grid → `counts` + `normalized` (busiest cell = 1.0), ready to shade.
- `guidance(stats)` — **post-video camera/tripod guidance** (SPEC Y6): the standing capture tips, plus a
  flag when a near-empty result points at a shaky/handheld camera a tripod would fix.
- Laptop-only: `extract_signal` / `cut_clips` / `process_video` (lazy cv2/ffmpeg). CLI:
  `python video.py match.mp4 out_dir` → `out_dir/stats.json` + `highlight_*.mp4`.

## Tier-1 ceilings (marked `ponytail:`; each upgrades to Tier 2 **after** Stage-0)

The frame-diff signal is deliberately the *simple* free approach — its **accuracy is exactly what
Stage-0 validates** before deeper vision (item #21). So, honestly bounded:

- motion = **frame-diff energy**, not ball/player boxes;
- shots = **motion-peak proxy**, not ball-contact detection;
- heatmap = **motion centroid**, not per-player tracks;
- reel ranks by **rally length**, not excitement scoring.

## Persistence — `migrations/block-20.sql` (SPEC Y5, owner-applied)

The uploaded stats JSON lands in a `video_stats` table (`id, owner, match?, stats jsonb, created_at`);
the highlight **clips** land in the existing `highlights` table (block-13). Stored whole as `jsonb` — the
tool owns the shape and it recomputes off the laptop, so nothing here must track the engine.
`PROPOSED / NOT APPLIED` like every block: **no session applies schema** — the owner applies it via the
Supabase MCP after block-16 (staged onto the item #19 apply card).

## Enforcement (same mechanism as items #2–#19)

- `deploy.py` `preflight()` calls `video.check()` beside `highlights.check()` / the rest. `check()`
  proves all four halves on a **synthetic** signal (two known rallies, a bridged mid-rally dip, two
  heatmap corners) — **no cv2, no video file** — plus JSON-serializability. A regression **aborts the
  deploy** before a file is uploaded. `check_migrations.check()` picks up `block-20.sql`.
- `test_video.py` is the runnable check (pytest): segmentation, the no-false-rally guards,
  counts/lengths + shots, the reel ordering/padding/clamping, the heatmap binning, and guidance.

## Scope (ponytail)

Built: the Tier-1 engine (rally segmentation, counts/lengths + shot estimate, highlight-reel spans,
movement heatmap, "max stats" JSON, capture guidance) + the laptop opencv/ffmpeg adapter + a runnable
check, wired into preflight; `block-20.sql` for the stats JSON; `requirements-video.txt` for the
laptop-only deps. **Skipped** (belongs elsewhere): **Tier 2** ball/player detection — gated on the
owner's real Stage-0 clip (item #21); the upload form / stats screen wiring (follow-on, after the
migration applies); audio in re-encoded clips (ffmpeg stream-copy keeps it when cutting). No new **web**
dependency, no schema applied, no money (free open-source libraries only).
