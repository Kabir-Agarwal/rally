"""Y6 Tier 1 video tool — rally segmentation, counts/lengths, highlight reel, movement heatmaps.

SPEC Y6 + owner ruling (14 Aug 2026): BUILD Y6 FRESH from free open-source vision libraries, LAST,
laptop-only processing; only the stats JSON + highlight clips upload (never the raw match video); the
Tier 1 set is exactly rally segmentation, rally counts/lengths, highlight reel, movement heatmaps.
Tier 2 (deeper vision) is GATED on the owner's real Stage-0 clip (item #21) — not this item.

Two layers, split on the dependency line — the same split highlights.py already names ("Decoding the
pixels ... is the Y6 laptop-only vision tool's job"):

  PURE ENGINE (this module's top half — stdlib only, zero dependencies)
    The brain. Everything Tier 1 measures is pure math over ONE motion signal + a motion centroid per
    sampled frame — no ML model, no ball tracker (that accuracy question IS Stage-0/Tier 2). Because it
    is dependency-free it runs in deploy.py preflight and ships to Vercel as a dormant pure module,
    exactly like the sibling engines (tournaments/leagues/highlights/...). check() proves it on a
    synthetic signal, no video file, no cv2.
      segment_rallies — threshold the motion signal, bridge brief dips, drop blips -> rally spans.
      analyze         — the one call the laptop adapter makes: rallies + counts/lengths + shot estimate
                        + highlight-reel spans + movement heatmap + capture guidance = the "max stats"
                        JSON that uploads (SPEC Y6: "upload stats JSON").
      highlight_reel  — pick the longest rallies (Tier-1 proxy for "best point"), pad + clamp -> clip
                        spans for the reel (the laptop adapter cuts the mp4s that upload).
      heatmap         — bin the rally-time motion centroids into a court grid -> movement coverage.
      guidance        — post-video camera/tripod tips (SPEC Y6), some conditional on what was detected.

  LAPTOP ADAPTER (bottom half — lazy-imports cv2/ffmpeg, NEVER imported at module load)
    process_video(path) — opencv frame-differencing turns real footage into the motion signal + centroids
    the engine consumes, writes stats.json, and cuts the highlight clips (ffmpeg stream-copy if present).
    Guarded so the web app / preflight never pull the heavy deps: `pip install -r requirements-video.txt`.

  # ponytail: Tier-1 ceilings, all upgrade to Tier 2 (ball/player detection) AFTER Stage-0 validates:
  #   motion = frame-diff energy, not ball/player boxes; shots = motion-peak proxy, not ball-contact;
  #   heatmap = motion centroid, not per-player tracks; reel ranks by rally length, not excitement.

Model — plain lists/dicts, JSON-serializable throughout (the payload IS an upload):
  motion     — list[float>=0], one per sampled frame: fraction of the frame that moved (high in a rally,
               low between points). fps is samples/second, so frame index i is at i/fps seconds.
  positions  — list[(x,y)] parallel to motion, each the motion centroid in normalized court coords
               [0,1]x[0,1]; (None, None) when a frame had no motion. Only rally-time centroids heat.
"""
from math import floor, ceil

# --- rally segmentation defaults (SPEC Y6: rally segmentation) --------------------------------
SENSITIVITY = 0.22      # active-frame threshold as a fraction of the clip's own [rest..peak] range
MIN_RALLY_S = 2.0       # shorter bursts are a player walking / camera jitter, not a rally
MAX_GAP_S = 1.0         # a brief dip (ball crossing, wind-up) inside a rally must not split it

# --- highlight reel defaults (SPEC Y6: highlight reel) ----------------------------------------
REEL_TOP_N = 5          # a reel is the few best points, not every rally
REEL_PAD_S = 1.5        # lead-in / lead-out so a clip does not start mid-swing

# --- heatmap defaults (SPEC Y6: movement heatmaps) --------------------------------------------
HEAT_ROWS, HEAT_COLS = 6, 6   # a coarse court grid — Tier-1 coverage, not pixel-accurate tracking

# --- post-video capture guidance (SPEC Y6: post-video camera/tripod guidance) -----------------
CAPTURE_GUIDANCE = (
    "Mount the camera on a TRIPOD — a handheld camera adds motion the tool cannot tell from play.",
    "Film LANDSCAPE (wide), from behind the baseline, high enough to see the whole court in frame.",
    "Keep the framing STILL for the whole match — do not pan or follow the ball; let players move in frame.",
    "Shoot in good, even light; avoid shooting into the sun so the players stay high-contrast.",
)


def _percentile(xs, p):
    """The p-th percentile (0-100) of xs by linear interpolation — stdlib stand-in for numpy."""
    s = sorted(xs)
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100.0
    lo, hi = floor(k), ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _median(xs):
    return _percentile(xs, 50)


def _auto_threshold(motion, sensitivity):
    """Active-frame cutoff, relative to THIS clip's own signal so it adapts to any camera/exposure:
    a fraction `sensitivity` of the way from the rest level (10th percentile — the quiet between points)
    up to the peak rally motion. A flat signal (peak==rest) yields a cutoff just above it, so nothing
    reads as a rally rather than everything."""
    if not motion:
        return 0.0
    rest = _percentile(motion, 10)
    peak = max(motion)
    if peak <= rest:
        return peak + 1e-9
    return rest + sensitivity * (peak - rest)


def segment_rallies(motion, fps, sensitivity=SENSITIVITY, min_rally_s=MIN_RALLY_S, max_gap_s=MAX_GAP_S):
    """Segment the per-frame motion signal into rallies (SPEC Y6: rally segmentation).

    A frame is *active* when its motion clears the auto threshold. A rally is a run of active frames,
    with two robustness rules so the count matches what a human would score: brief inactive dips up to
    `max_gap_s` (a ball crossing, a wind-up between shots) are BRIDGED rather than splitting the rally;
    and runs shorter than `min_rally_s` are DROPPED (a player walking to position is not a rally).

    Returns a list of rallies in play order, each:
      {"index", "start_s", "end_s", "duration_s", "frames": [first, last]}   (frame indices inclusive)
    """
    fps = float(fps)
    if not motion or fps <= 0:
        return []
    thr = _auto_threshold(motion, sensitivity)
    max_gap = max(1, round(max_gap_s * fps))
    min_len = max(1, round(min_rally_s * fps))

    segs, start, last_active, gap = [], None, None, 0
    for i, m in enumerate(motion):
        if m >= thr:                       # active frame
            if start is None:
                start = i
            last_active, gap = i, 0
        elif start is not None:            # inactive frame inside an open rally
            gap += 1
            if gap > max_gap:              # dip too long — the rally ended at the last active frame
                segs.append((start, last_active))
                start = None
    if start is not None:
        segs.append((start, last_active))

    rallies = []
    for a, b in segs:
        if b - a + 1 >= min_len:
            rallies.append({
                "index": len(rallies),
                "start_s": round(a / fps, 2),
                "end_s": round((b + 1) / fps, 2),      # +1: the last active frame's footage is covered
                "duration_s": round((b - a + 1) / fps, 2),
                "frames": [a, b],
            })
    return rallies


def _count_shots(seg_motion, fps, thr):
    """Estimate shots in a rally by counting motion peaks (local maxima above the active threshold),
    with a minimum spacing so one swing's burst is not double-counted. A proxy, not ball-contact
    detection.  # ponytail: motion-peak proxy; real shot detection needs ball tracking (Tier 2)."""
    min_sep = max(1, round(0.35 * fps))    # ~0.35s: a player cannot hit two shots closer than this
    shots, last = 0, -min_sep
    for i in range(1, len(seg_motion) - 1):
        m = seg_motion[i]
        if m > thr and m >= seg_motion[i - 1] and m > seg_motion[i + 1] and i - last >= min_sep:
            shots, last = shots + 1, i
    return shots


def highlight_reel(rallies, video_duration_s, top_n=REEL_TOP_N, pad_s=REEL_PAD_S):
    """Pick the highlight-reel clip spans (SPEC Y6: highlight reel): the `top_n` longest rallies — the
    Tier-1 proxy for the best points — each padded by `pad_s` on both sides and clamped to the video,
    returned in play order as {"rally_index", "start_s", "end_s", "duration_s"}. The laptop adapter
    cuts the mp4s from these spans; those clips are what upload (SPEC Y6), never the raw match.
    # ponytail: ranks by rally length; excitement scoring (pace, net play) is Tier 2."""
    ranked = sorted(rallies, key=lambda r: r["duration_s"], reverse=True)[:max(0, top_n)]
    clips = []
    for r in ranked:
        s = max(0.0, r["start_s"] - pad_s)
        e = min(float(video_duration_s), r["end_s"] + pad_s) if video_duration_s else r["end_s"] + pad_s
        clips.append({"rally_index": r["index"], "start_s": round(s, 2),
                      "end_s": round(e, 2), "duration_s": round(e - s, 2)})
    clips.sort(key=lambda c: c["start_s"])
    return clips


def heatmap(positions, rows=HEAT_ROWS, cols=HEAT_COLS):
    """Bin motion centroids into a court grid -> movement heatmap (SPEC Y6: movement heatmaps).

    `positions` are (x, y) in normalized court coords [0,1]; (None, _) frames (no motion) are skipped.
    Returns {"rows","cols","samples","counts": rows x cols ints, "normalized": rows x cols in [0,1]}
    where normalized divides by the busiest cell — a ready-to-shade coverage grid.
    # ponytail: bins the motion centroid, not per-player tracks; two-player split is Tier 2."""
    grid = [[0] * cols for _ in range(rows)]
    used = 0
    for x, y in positions:
        if x is None or y is None:
            continue
        c = min(cols - 1, max(0, int(x * cols)))
        r = min(rows - 1, max(0, int(y * rows)))
        grid[r][c] += 1
        used += 1
    peak = max((v for row in grid for v in row), default=0)
    norm = [[round(v / peak, 3) if peak else 0.0 for v in row] for row in grid]
    return {"rows": rows, "cols": cols, "samples": used, "counts": grid, "normalized": norm}


def guidance(stats):
    """Post-video camera/tripod guidance (SPEC Y6). The standing capture tips, plus a note when the
    result suggests a capture problem — almost no sustained rally usually means a shaky/handheld camera
    or a framing that misses the court, which a tripod fixes."""
    tips = list(CAPTURE_GUIDANCE)
    lengths, rallies = stats["lengths"], stats["rallies"]
    if rallies["count"] == 0:
        tips.insert(0, "No rallies detected — check the camera saw the whole court, level and still on a "
                       "tripod; a panning or handheld shot hides the rallies.")
    elif lengths["active_ratio"] < 0.10:
        tips.insert(0, "Very little sustained play detected — if the match was busier than that, the "
                       "camera was likely moving; lock it on a tripod so only the players move in frame.")
    return tips


def analyze(motion, positions, fps, duration_s=None, *, sensitivity=SENSITIVITY,
            min_rally_s=MIN_RALLY_S, max_gap_s=MAX_GAP_S, top_n=REEL_TOP_N, pad_s=REEL_PAD_S,
            heat_rows=HEAT_ROWS, heat_cols=HEAT_COLS, source=None):
    """The one call the laptop adapter makes: motion signal + centroids -> the full Tier-1 stats dict,
    JSON-serializable, that uploads (SPEC Y6: "upload stats JSON"). Ties the four Tier-1 halves together
    the way nearby.discover()/highlights.card() join theirs. "max stats" (SPEC Y6): every number the two
    input signals support — rally spans + shot estimates, the length aggregates, the reel spans, the
    movement heatmap, and the capture guidance."""
    fps = float(fps) or 1.0
    if duration_s is None:
        duration_s = len(motion) / fps if motion else 0.0

    rallies = segment_rallies(motion, fps, sensitivity, min_rally_s, max_gap_s)
    thr = _auto_threshold(motion, sensitivity)
    for r in rallies:
        a, b = r["frames"]
        r["shots"] = _count_shots(motion[a:b + 1], fps, thr)

    durations = [r["duration_s"] for r in rallies]
    total_shots = sum(r["shots"] for r in rallies)
    total_play = round(sum(durations), 2)

    reel = highlight_reel(rallies, duration_s, top_n, pad_s)

    rally_pos = []
    for r in rallies:
        a, b = r["frames"]
        rally_pos.extend(positions[a:b + 1])
    heat = heatmap(rally_pos, heat_rows, heat_cols)

    stats = {
        "tool": "rally-video", "tier": 1, "spec": "Y6",
        "source": source or {"fps": round(fps, 3), "duration_s": round(duration_s, 2),
                             "frames": len(motion)},
        "rallies": {"count": len(rallies), "list": rallies},
        "lengths": {
            "total_play_s": total_play,
            "active_ratio": round(total_play / duration_s, 3) if duration_s else 0.0,
            "longest_s": max(durations) if durations else 0.0,
            "shortest_s": min(durations) if durations else 0.0,
            "avg_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "median_s": round(_median(durations), 2) if durations else 0.0,
            "total_shots": total_shots,
            "avg_shots_per_rally": round(total_shots / len(rallies), 1) if rallies else 0.0,
        },
        "highlight_reel": reel,
        "heatmap": heat,
    }
    stats["guidance"] = guidance(stats)
    return stats


# =============================================================================================
# LAPTOP ADAPTER — lazy-imports cv2 / ffmpeg. NOTHING above this line imports them, so the web app
# and deploy.py preflight stay dependency-free. Runs only on the owner's laptop (SPEC Y6 laptop-only).
# =============================================================================================
def _lazy_cv2():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError as e:                      # pragma: no cover - laptop-only path
        raise RuntimeError("Y6 video tool is laptop-only — install the vision deps first:\n"
                           "    pip install -r requirements-video.txt") from e


def extract_signal(path, sample_every=3, work_w=160, work_h=90):
    """Laptop-only: opencv frame-differencing turns a match video into the (motion, positions, fps)
    the pure engine consumes. Frames are downscaled to work_w x work_h (motion energy is scale-free) and
    only every `sample_every`-th frame is read, so a full match processes in minutes on a laptop.
    # ponytail: frame-diff energy + centroid; ball/player detection (better accuracy) is Tier 2."""
    cv2, np = _lazy_cv2()
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():                        # pragma: no cover - laptop-only path
        raise RuntimeError(f"cannot open video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    motion, positions, prev, idx = [], [], None, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % sample_every == 0:
            gray = cv2.cvtColor(cv2.resize(frame, (work_w, work_h)), cv2.COLOR_BGR2GRAY)
            if prev is not None:
                diff = cv2.absdiff(gray, prev)
                _, mask = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
                motion.append(float(mask.mean()) / 255.0)
                m = cv2.moments(mask)
                if m["m00"] > 0:
                    positions.append((m["m10"] / m["m00"] / work_w, m["m01"] / m["m00"] / work_h))
                else:
                    positions.append((None, None))
            prev = gray
        idx += 1
    cap.release()
    return {"motion": motion, "positions": positions, "fps": src_fps / sample_every,
            "duration_s": idx / src_fps if src_fps else 0.0,
            "width": width, "height": height, "frames": idx}


def cut_clips(path, reel, out_dir):
    """Cut the highlight-reel spans into mp4 clips with ffmpeg stream-copy (keeps audio, no re-encode).
    Returns the clip paths made. If ffmpeg is not on PATH, returns [] — the spans are already in
    stats.json for the owner to cut. Only these clips (never the raw match) upload (SPEC Y6)."""
    import os
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg")
    if not ff:                                    # pragma: no cover - laptop-only path
        return []
    made = []
    for i, c in enumerate(reel, 1):
        out = os.path.join(out_dir, f"highlight_{i}.mp4")
        subprocess.run([ff, "-y", "-ss", str(c["start_s"]), "-i", path, "-t", str(c["duration_s"]),
                        "-c", "copy", out], check=True, capture_output=True)
        made.append(out)
    return made


def process_video(path, out_dir=".", write_clips=True, **opts):
    """Laptop-only end to end (SPEC Y6): read the match video, analyze it, write stats.json, and cut the
    highlight clips. Returns the stats dict. Only stats.json + the clips are meant to upload — the raw
    match video never leaves the laptop."""
    import os
    import json
    sig = extract_signal(path, opts.pop("sample_every", 3))
    stats = analyze(sig["motion"], sig["positions"], sig["fps"], sig["duration_s"],
                    source={k: sig[k] for k in ("fps", "duration_s", "frames", "width", "height")},
                    **opts)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    stats["clips"] = cut_clips(path, stats["highlight_reel"], out_dir) if write_clips else []
    return stats


# =============================================================================================
def _synthetic():
    """A deterministic motion signal + centroids with two known rallies, for check()/tests — no cv2,
    no video file. fps=10; a ~4.4s rally then a ~4.0s rally, separated/surrounded by quiet, with a 0.4s
    dip inside the first rally (must be BRIDGED, not split it into two). The 0.9/0.4 oscillation gives
    the shot-peak counter something to find. Centroids alternate two court corners."""
    fps = 10
    quiet = [0.04] * 30                        # 3.0s between-point rest
    r1 = ([0.9, 0.4] * 10) + ([0.05] * 4) + ([0.9, 0.4] * 10)   # 4.4s span rally with a 0.4s mid dip
    gap = [0.04] * 20                          # 2.0s rest between points
    r2 = [0.85, 0.35] * 20                     # 4.0s rally
    motion = quiet + r1 + gap + r2 + quiet
    positions = []
    for i, m in enumerate(motion):
        if m >= 0.2:                           # an active frame: alternate two opposite court corners
            positions.append((0.2, 0.8) if i % 2 == 0 else (0.8, 0.2))
        else:                                  # a quiet/dip frame: no motion, so no centroid
            positions.append((None, None))
    return motion, positions, fps


def check():
    """Fail loud (ValueError) if the Tier-1 video engine regressed. Zero deps — no cv2, no video file.
    Wired into deploy.py preflight beside the sibling engine check()s."""
    import json
    bad = []
    motion, positions, fps = _synthetic()

    # 1. RALLY SEGMENTATION — the two real rallies are found; the 0.5s mid-rally dip is BRIDGED (not a
    #    third rally), the between-point quiet is not a rally, and durations match ~5s and ~4s.
    rallies = segment_rallies(motion, fps)
    if len(rallies) != 2:
        bad.append(f"segment_rallies found {len(rallies)} rallies, want 2 (dip must bridge, quiet must not count)")
    else:
        d0, d1 = rallies[0]["duration_s"], rallies[1]["duration_s"]
        if not (4.0 <= d0 <= 4.8):
            bad.append(f"rally 1 duration {d0}s, want ~4.4 (the mid-rally dip was not bridged)")
        if not (3.6 <= d1 <= 4.4):
            bad.append(f"rally 2 duration {d1}s, want ~4.0")
        if rallies[0]["start_s"] >= rallies[1]["start_s"]:
            bad.append("rallies not returned in play order")

    # a blip shorter than MIN_RALLY_S is not a rally; an empty/flat signal yields none (not an error).
    if segment_rallies([0.9] * 5 + [0.04] * 30, fps):     # 0.5s burst < 2s floor
        bad.append("a sub-min_rally blip was counted as a rally")
    if segment_rallies([], fps) or segment_rallies([0.5] * 40, fps):
        bad.append("empty / perfectly flat signal should yield no rallies")

    # 2. COUNTS / LENGTHS + shot estimate — analyze() aggregates, active_ratio in (0,1), each rally has
    #    a positive shot estimate, and the whole payload is JSON-serializable (it is an upload).
    stats = analyze(motion, positions, fps)
    L = stats["lengths"]
    if stats["rallies"]["count"] != 2:
        bad.append(f"analyze rally count {stats['rallies']['count']}, want 2")
    if not (0.0 < L["active_ratio"] < 1.0):
        bad.append(f"active_ratio {L['active_ratio']} should be a fraction in (0,1)")
    if L["longest_s"] < L["shortest_s"] or not (L["shortest_s"] <= L["avg_s"] <= L["longest_s"]):
        bad.append(f"length aggregates inconsistent: {L}")
    if any(r["shots"] <= 0 for r in stats["rallies"]["list"]):
        bad.append("every detected rally should estimate >=1 shot")
    if L["total_shots"] <= 0 or L["avg_shots_per_rally"] <= 0:
        bad.append("shot totals should be positive when rallies exist")
    try:
        json.dumps(stats)
    except (TypeError, ValueError) as e:
        bad.append(f"stats payload is not JSON-serializable: {e}")

    # 3. HIGHLIGHT REEL — one clip per rally here, in play order, padded, clamped inside the video, and
    #    each spans at least its rally. top_n caps the count.
    reel = stats["highlight_reel"]
    if len(reel) != 2:
        bad.append(f"reel has {len(reel)} clips, want 2 (one per rally)")
    if reel and (reel[0]["start_s"] > reel[-1]["start_s"]):
        bad.append("reel clips not in play order")
    dur = stats["source"]["duration_s"]
    for c in reel:
        if c["start_s"] < 0 or c["end_s"] > dur + 1e-6 or c["end_s"] <= c["start_s"]:
            bad.append(f"reel clip out of bounds / inverted: {c} (video {dur}s)")
    if len(highlight_reel(rallies, dur, top_n=1)) != 1:
        bad.append("top_n did not cap the reel length")

    # 4. MOVEMENT HEATMAP — the two alternating corners land in two distinct cells; counts sum to the
    #    rally-time samples; the busiest cell normalizes to 1.0; a bin is inside the grid.
    heat = stats["heatmap"]
    hot = [(r, c) for r in range(heat["rows"]) for c in range(heat["cols"]) if heat["counts"][r][c] > 0]
    if len(hot) != 2:
        bad.append(f"heatmap lit {len(hot)} cells, want 2 (two corners)")
    if sum(v for row in heat["counts"] for v in row) != heat["samples"] or heat["samples"] <= 0:
        bad.append("heatmap counts must sum to its sample total")
    if heat["samples"] and max(v for row in heat["normalized"] for v in row) != 1.0:
        bad.append("busiest heatmap cell should normalize to 1.0")
    only = heatmap([(0.9, 0.9)], rows=4, cols=4)          # bottom-right corner -> last cell, in-bounds
    if only["counts"][3][3] != 1 or only["samples"] != 1:
        bad.append("heatmap mis-binned a corner sample")

    # 5. GUIDANCE — always present; flags a near-empty result as a likely capture (tripod) problem.
    if not stats["guidance"] or not any("tripod" in t.lower() for t in stats["guidance"]):
        bad.append("guidance must always include the tripod capture tips")
    empty = analyze([0.05] * 50, [(None, None)] * 50, fps)   # no play -> capture-problem hint
    if not any("no rall" in t.lower() or "little sustained" in t.lower() for t in empty["guidance"]):
        bad.append("guidance should hint at a capture problem when nothing was detected")

    if bad:
        raise ValueError("video Tier-1 engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:                                       # laptop tool: python video.py match.mp4 [out_dir]
        out = args[1] if len(args) > 1 else "video-out"
        s = process_video(args[0], out_dir=out)
        print(f"analyzed {args[0]}: {s['rallies']['count']} rallies, "
              f"{s['lengths']['total_play_s']}s play, {len(s['highlight_reel'])} reel clips, "
              f"{len(s.get('clips', []))} cut -> {out}/stats.json")
    else:                                          # deps-free self-check
        check()
        print("video OK: Tier-1 engine (rally segmentation, counts/lengths, highlight reel, heatmaps) — "
              "laptop adapter behind cv2/ffmpeg; only stats JSON + clips upload (SPEC Y6)")
