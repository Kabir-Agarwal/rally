"""Y6 Stage-0 gate — Y6 Tier 2 (deeper vision) stays LOCKED until the owner's real clip validates.

SPEC Y6: "Stage-0 accuracy test runs ... before any deeper vision work." Owner ruling (14 Aug 2026):
"Tier 2 only after the owner's real Stage-0 clip validates." Item #20 shipped the Tier-1 engine on a
deliberately simple frame-diff motion signal whose ACCURACY IS UNPROVEN on real footage — that unproven
accuracy is exactly what Stage-0 measures before anyone builds ball/player detection (Tier 2) on top of
it. This module IS that gate. It does NOT build Tier 2 (owner: not yet).

How the gate works — it fails CLOSED:
  * The owner hand-labels ONE real match clip: each rally's start/end seconds — the ground truth a human
    scoring the clip already has in their head. Cheapest honest label; no ML needed to produce it.
  * validate(clip, labels) runs the Tier-1 tool (video.process_video) on that SAME real clip and scores
    the tool's detected rallies against the labels by temporal IoU -> recall / precision / mean-IoU.
  * It records stage0_verdict.json: PASS only if every accuracy metric clears its threshold.
  * require_tier2_unlocked() is the guard every future Tier 2 entrypoint calls FIRST. It RECOMPUTES
    pass/fail from the recorded metrics (never trusts the verdict's "result" string) against thresholds
    that can only be made STRICTER, not looser, than the built-ins here. So a missing, malformed, FAIL,
    or hand-edited verdict all leave Tier 2 LOCKED — only a genuine recorded pass unlocks it.

Pure stdlib (scoring + gate + check) — ships to Vercel dormant and runs in deploy.py preflight beside
the sibling engines. Only validate() touches vision: it calls video.process_video, laptop-only, which
lazy-imports cv2. check()/tests never write the verdict, so preflight can never accidentally unlock.
"""
import os
import json

# --- Stage-0 accuracy bar (owner-tunable, but the gate only ever tightens these, never loosens) ------
IOU_MIN = 0.30         # a labeled rally counts as "found" if some detection overlaps it at least this
RECALL_MIN = 0.80      # ...and Stage-0 passes only if the tool finds >=80% of the real rallies,
PREC_MIN = 0.80        # ...with <=20% of its detections spurious (precision),
IOU_MEAN_MIN = 0.50    # ...and the matched spans overlap the real ones at least half on average.
THRESHOLDS = {"recall_min": RECALL_MIN, "prec_min": PREC_MIN, "iou_mean_min": IOU_MEAN_MIN}

VERDICT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage0_verdict.json")
_UNSET = object()      # sentinel so tier2_unlocked(None) means "no verdict" without reading the file


def _secs(v):
    """Seconds from a number or a 'm:ss' / 'h:mm:ss' string (a human labels a clip off the clock)."""
    if isinstance(v, (int, float)):
        return float(v)
    s = 0.0
    for part in str(v).split(":"):
        s = s * 60 + float(part)
    return s


def _spans(rallies):
    """[(start,end)] from either labels or tool rallies — both carry start_s/end_s."""
    return [(_secs(r["start_s"]), _secs(r["end_s"])) for r in rallies]


def _iou(a, b):
    """Temporal intersection-over-union of two [start,end] second-intervals (0 when disjoint)."""
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def score(labels, stats):
    """Score the Tier-1 tool's detected rallies (stats from video.analyze) against the owner's hand
    labels. Greedy IoU matching: each labeled rally takes its best-overlap still-unused detection above
    IOU_MIN. Returns the accuracy metrics Stage-0 judges — recall, precision, mean matched IoU.
    # ponytail: greedy interval matching; Hungarian only if dozens of rallies ever need optimal pairing."""
    truth = _spans(labels["rallies"])
    got = _spans(stats["rallies"]["list"])
    used, ious, hits = set(), [], 0
    for t in truth:
        best, best_j = 0.0, None
        for j, g in enumerate(got):
            if j in used:
                continue
            v = _iou(t, g)
            if v > best:
                best, best_j = v, j
        if best_j is not None and best >= IOU_MIN:
            used.add(best_j)
            ious.append(best)
            hits += 1
    n_truth, n_got = len(truth), len(got)
    return {
        "labeled": n_truth, "detected": n_got, "matched": hits,
        "count_error": abs(n_got - n_truth),
        "recall": round(hits / n_truth, 3) if n_truth else 0.0,
        "precision": round(hits / n_got, 3) if n_got else 0.0,
        "mean_iou": round(sum(ious) / len(ious), 3) if ious else 0.0,
    }


def passed(metrics, thresholds=THRESHOLDS):
    """PASS/FAIL from metrics vs thresholds, with the specific reasons for a fail. The gate calls this
    on the RECORDED metrics — a verdict's own "result" string is never trusted on its own."""
    reasons = []
    if metrics.get("labeled", 0) <= 0:
        reasons.append("no labeled rallies — Stage-0 needs the owner's ground truth for a real clip")
    if metrics.get("recall", 0.0) < thresholds["recall_min"]:
        reasons.append(f"recall {metrics.get('recall')} < {thresholds['recall_min']} (missed real rallies)")
    if metrics.get("precision", 0.0) < thresholds["prec_min"]:
        reasons.append(f"precision {metrics.get('precision')} < {thresholds['prec_min']} (spurious detections)")
    if metrics.get("mean_iou", 0.0) < thresholds["iou_mean_min"]:
        reasons.append(f"mean IoU {metrics.get('mean_iou')} < {thresholds['iou_mean_min']} (spans off the real ones)")
    return (not reasons), reasons


# =====================================================================================================
# THE GATE — fail-closed. Every future Y6 Tier 2 entrypoint's first line is require_tier2_unlocked().
# =====================================================================================================
class Tier2Locked(RuntimeError):
    """Raised while Y6 Tier 2 is gated. Deeper-vision code must call the guard first; catching this to
    proceed anyway defeats the gate the owner asked for."""


def load_verdict(path=VERDICT_FILE):
    """The recorded Stage-0 verdict, or None if the owner has not validated a real clip yet / it is
    unreadable. Missing or corrupt both read as 'not validated' (locked)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None


def tier2_unlocked(verdict=_UNSET):
    """True only if a Stage-0 verdict is recorded AND its own metrics still clear the thresholds. The
    recorded thresholds may be TIGHTER than the built-ins but never looser (editing them down to cheat
    is ignored), and any malformed field fails closed."""
    if verdict is _UNSET:
        verdict = load_verdict()
    if not isinstance(verdict, dict):
        return False
    metrics = verdict.get("metrics")
    if not isinstance(metrics, dict):
        return False
    rec = verdict.get("thresholds") if isinstance(verdict.get("thresholds"), dict) else {}
    try:
        strict = {k: max(v, float(rec.get(k, v))) for k, v in THRESHOLDS.items()}
        ok, _ = passed(metrics, strict)
        return ok
    except (KeyError, TypeError, ValueError):
        return False


def require_tier2_unlocked(verdict=_UNSET):
    """GATE — the required first line of every future Y6 Tier 2 (deeper-vision) entrypoint. Raises
    Tier2Locked unless the owner's real Stage-0 clip has validated (STATUS card / docs/item-21-...)."""
    if not tier2_unlocked(verdict):
        raise Tier2Locked(
            "Y6 Tier 2 (deeper vision) is LOCKED until the owner's real Stage-0 clip validates.\n"
            "Run:  python stage0.py <real-clip.mp4> <labels.json>   (see docs/item-21-stage0-gate.md)")


# =====================================================================================================
# LAPTOP-ONLY — the real Stage-0 run. Reuses video.process_video (lazy-imports cv2). This is the ONLY
# path that writes the verdict; running check()/tests never does, so preflight can't unlock Tier 2.
# =====================================================================================================
def validate(clip_path, labels_path, out=VERDICT_FILE, out_dir="video-out", **opts):
    """Process the owner's REAL clip with the Tier-1 tool, score it against the hand labels, record the
    verdict the gate reads, and return it. labels JSON: {"rallies": [{"start_s","end_s"}, ...]}."""
    import video
    with open(labels_path, encoding="utf-8") as f:
        labels = json.load(f)
    stats = video.process_video(clip_path, out_dir=out_dir, **opts)
    metrics = score(labels, stats)
    ok, reasons = passed(metrics)
    verdict = {
        "stage": 0, "spec": "Y6", "gate": "Y6 Tier 2",
        "result": "PASS" if ok else "FAIL",
        "unlocks_tier2": ok,
        "clip": os.path.basename(clip_path),
        "labels": os.path.basename(labels_path),
        "metrics": metrics, "thresholds": THRESHOLDS,
        "reasons": reasons or ["all Stage-0 accuracy thresholds met"],
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2)
    return verdict


# =====================================================================================================
def check():
    """Fail loud (ValueError) if the Stage-0 gate regressed. Zero deps, and NEVER touches the real
    stage0_verdict.json — it exercises score/passed/the gate on in-memory verdicts only, so running it
    (deploy.py preflight) can never unlock Tier 2. Wired in beside video.check()."""
    import video
    bad = []
    motion, positions, fps = video._synthetic()
    stats = video.analyze(motion, positions, fps)
    det = stats["rallies"]["list"]
    if len(det) != 2:
        raise ValueError("stage0.check expects video._synthetic's 2 rallies; the video engine changed")

    # 1. A tool run that matches the labels exactly -> PASS (use the detected spans as ground truth).
    good = {"rallies": [{"start_s": r["start_s"], "end_s": r["end_s"]} for r in det]}
    gm = score(good, stats)
    ok, reasons = passed(gm)
    if not ok:
        bad.append(f"a perfect match should PASS Stage-0, got reasons {reasons} from {gm}")
    if not (gm["recall"] == 1.0 and gm["precision"] == 1.0 and gm["mean_iou"] > 0.99):
        bad.append(f"perfect-match metrics wrong: {gm}")

    # 2. A tool run that detects nothing where the clip had rallies -> FAIL (recall 0).
    fm = score(good, {"rallies": {"list": []}})
    if passed(fm)[0]:
        bad.append("missing every rally must FAIL Stage-0")
    # ...and detections that overlap no real rally -> also FAIL (no matches).
    off = {"rallies": {"list": [{"start_s": 900, "end_s": 903}, {"start_s": 910, "end_s": 914}]}}
    if passed(score(good, off))[0]:
        bad.append("detections that overlap no real rally must FAIL Stage-0")
    # ...and 'm:ss' labels parse the same as seconds (a human writes 1:00, not 60).
    if score({"rallies": [{"start_s": "0:03", "end_s": "0:07"}]},
             {"rallies": {"list": [{"start_s": 3.0, "end_s": 7.0}]}})["mean_iou"] != 1.0:
        bad.append("'m:ss' labels must parse to the same seconds")

    # 3. THE GATE fails CLOSED — locked unless a recorded pass whose metrics clear the thresholds.
    if tier2_unlocked(None):
        bad.append("gate must be LOCKED when no Stage-0 verdict is recorded")
    if tier2_unlocked({}) or tier2_unlocked({"result": "PASS"}):
        bad.append("gate must not unlock on a malformed / result-only verdict (no real metrics)")
    if tier2_unlocked({"metrics": fm, "thresholds": THRESHOLDS}):
        bad.append("gate must stay LOCKED on a recorded FAIL's metrics")
    # a passing verdict whose thresholds were hand-lowered to cheat is ignored -> stays locked.
    if tier2_unlocked({"metrics": {"labeled": 1, "recall": 0.1, "precision": 0.1, "mean_iou": 0.1},
                       "thresholds": {"recall_min": 0.0, "prec_min": 0.0, "iou_mean_min": 0.0}}):
        bad.append("gate must ignore hand-lowered thresholds (only tighten, never loosen)")
    if not tier2_unlocked({"metrics": gm, "thresholds": THRESHOLDS}):
        bad.append("gate must UNLOCK on a recorded pass whose metrics clear the thresholds")
    try:
        require_tier2_unlocked(None)
        bad.append("require_tier2_unlocked must raise Tier2Locked while locked")
    except Tier2Locked:
        pass

    if bad:
        raise ValueError("Y6 Stage-0 gate regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) >= 2:                             # laptop: python stage0.py real-clip.mp4 labels.json
        v = validate(args[0], args[1])
        print(json.dumps(v, indent=2))
        print("\nY6 Tier 2:", "UNLOCKED — deeper vision may proceed." if v["unlocks_tier2"]
              else "still LOCKED — the frame-diff signal missed the Stage-0 bar (see reasons above).")
        sys.exit(0 if v["unlocks_tier2"] else 1)
    check()                                        # deps-free self-check (also run in deploy preflight)
    print("stage0 OK: gate logic holds; Y6 Tier 2 is currently",
          "UNLOCKED" if tier2_unlocked() else "LOCKED (no passing Stage-0 verdict recorded)", "(SPEC Y6)")
