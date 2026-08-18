"""Y6 Tier 1 video tool — rally segmentation, counts/lengths, highlight reel, movement heatmaps.

Proves the pure engine the laptop-only Y6 tool runs on (SPEC Y6 + owner ruling): segment a motion
signal into rallies (bridging brief dips, dropping blips), count/measure them + estimate shots, pick
the highlight-reel clip spans, bin motion centroids into a movement heatmap, and assemble the JSON
stats payload + post-video capture guidance that upload. Dependency-free: no cv2, no video file — the
opencv/ffmpeg adapter is the laptop half and is not exercised here.
"""
import json

import pytest

import video as V


def test_check_holds():
    assert V.check() is True                                       # the real engine self-check


def test_segments_two_rallies_bridging_the_dip():
    motion, _positions, fps = V._synthetic()
    rallies = V.segment_rallies(motion, fps)
    assert len(rallies) == 2                                       # the mid-rally dip bridged, quiet ignored
    assert 4.0 <= rallies[0]["duration_s"] <= 4.8                  # ~4.4s (dip bridged, not split)
    assert 3.6 <= rallies[1]["duration_s"] <= 4.4                  # ~4.0s
    assert rallies[0]["start_s"] < rallies[1]["start_s"]           # returned in play order


@pytest.mark.parametrize("motion,why", [
    ([0.9] * 5 + [0.04] * 30, "a 0.5s burst is under the 2s rally floor"),
    ([], "empty signal"),
    ([0.5] * 40, "a perfectly flat signal has no rally above rest"),
])
def test_no_false_rallies(motion, why):
    assert V.segment_rallies(motion, 10) == []


def test_analyze_aggregates_and_is_json_serializable():
    motion, positions, fps = V._synthetic()
    stats = V.analyze(motion, positions, fps)
    L = stats["lengths"]
    assert stats["rallies"]["count"] == 2
    assert 0.0 < L["active_ratio"] < 1.0                           # a fraction of the clip was play
    assert L["shortest_s"] <= L["avg_s"] <= L["longest_s"]
    assert all(r["shots"] >= 1 for r in stats["rallies"]["list"])  # each rally estimates >=1 shot
    assert L["total_shots"] > 0
    json.dumps(stats)                                              # the payload IS an upload — must serialize


def test_highlight_reel_is_ordered_padded_and_clamped():
    motion, positions, fps = V._synthetic()
    stats = V.analyze(motion, positions, fps)
    reel, dur = stats["highlight_reel"], stats["source"]["duration_s"]
    assert len(reel) == 2                                          # one clip per rally
    assert [c["start_s"] for c in reel] == sorted(c["start_s"] for c in reel)  # play order
    for c in reel:
        assert 0 <= c["start_s"] < c["end_s"] <= dur + 1e-6        # padded but clamped inside the video
    assert len(V.highlight_reel(stats["rallies"]["list"], dur, top_n=1)) == 1  # top_n caps the reel


def test_heatmap_bins_corners_and_normalizes():
    motion, positions, fps = V._synthetic()
    heat = V.analyze(motion, positions, fps)["heatmap"]
    lit = [(r, c) for r in range(heat["rows"]) for c in range(heat["cols"]) if heat["counts"][r][c]]
    assert len(lit) == 2                                           # the two alternating corners
    assert sum(v for row in heat["counts"] for v in row) == heat["samples"] > 0
    assert max(v for row in heat["normalized"] for v in row) == 1.0  # busiest cell normalizes to 1.0
    corner = V.heatmap([(0.9, 0.9)], rows=4, cols=4)               # bottom-right -> last cell, in-bounds
    assert corner["counts"][3][3] == 1 and corner["samples"] == 1


def test_guidance_always_present_and_flags_empty_capture():
    motion, positions, fps = V._synthetic()
    tips = V.analyze(motion, positions, fps)["guidance"]
    assert tips and any("tripod" in t.lower() for t in tips)       # the standing capture tips
    empty = V.analyze([0.05] * 50, [(None, None)] * 50, fps)       # nothing detected -> capture hint
    assert any("no rall" in t.lower() or "little sustained" in t.lower() for t in empty["guidance"])
