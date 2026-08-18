"""Y6 Stage-0 gate — Tier 2 stays LOCKED until the owner's real clip validates (SPEC Y6).

Proves the gate fails CLOSED: scoring a real-clip run against hand labels (temporal IoU -> recall /
precision / mean-IoU), the PASS/FAIL bar, and — the point of the item — that require_tier2_unlocked()
raises unless a genuine passing verdict is recorded, and that a hand-edited verdict cannot cheat it.
Dependency-free: no cv2, no video file (validate() is the laptop half and is not exercised here).
"""
import stage0 as S
import video as V


def test_check_holds():
    assert S.check() is True                                        # the real gate self-check


def _perfect_labels_and_stats():
    motion, positions, fps = V._synthetic()
    stats = V.analyze(motion, positions, fps)
    det = stats["rallies"]["list"]
    labels = {"rallies": [{"start_s": r["start_s"], "end_s": r["end_s"]} for r in det]}
    return labels, stats


def test_perfect_match_passes():
    labels, stats = _perfect_labels_and_stats()
    m = S.score(labels, stats)
    assert m["recall"] == 1.0 and m["precision"] == 1.0 and m["mean_iou"] > 0.99
    assert S.passed(m)[0] is True


def test_missing_and_off_target_detections_fail():
    labels, _ = _perfect_labels_and_stats()
    assert S.passed(S.score(labels, {"rallies": {"list": []}}))[0] is False          # found nothing
    off = {"rallies": {"list": [{"start_s": 900, "end_s": 903}]}}                     # overlaps nothing
    assert S.passed(S.score(labels, off))[0] is False


def test_gate_is_locked_by_default_and_raises():
    assert S.tier2_unlocked(None) is False                          # no verdict recorded -> locked
    assert S.tier2_unlocked({"result": "PASS"}) is False            # a bare string cannot unlock
    with __import__("pytest").raises(S.Tier2Locked):
        S.require_tier2_unlocked(None)


def test_gate_ignores_hand_lowered_thresholds_but_opens_on_a_real_pass():
    labels, stats = _perfect_labels_and_stats()
    good = S.score(labels, stats)
    assert S.tier2_unlocked({"metrics": good, "thresholds": S.THRESHOLDS}) is True    # a genuine pass
    cheat = {"metrics": {"labeled": 1, "recall": 0.1, "precision": 0.1, "mean_iou": 0.1},
             "thresholds": {"recall_min": 0.0, "prec_min": 0.0, "iou_mean_min": 0.0}}
    assert S.tier2_unlocked(cheat) is False                         # lowering the bar to cheat is ignored
