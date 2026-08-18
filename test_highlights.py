"""Highlights — landscape video upload + reputation stars + laurels (SPEC Y3 — ADD highlights).

Proves the engine the highlights feature-block is built on: the landscape upload gate (accept a wide
clip, refuse portrait/square/unknown-format/oversize/over-long with a reason), the 1–5★ reputation
model (one vote per viewer, no self-rating), and the earned laurels (none->bronze->silver->gold over a
votes floor, so one rave vote earns nothing).
"""
import pytest

import highlights as H


def test_check_holds():
    assert H.check() is True                                       # the real engine self-check


def test_accept_upload_takes_landscape_and_tags_aspect():
    ok = H.accept_upload({"width": 1920, "height": 1080, "duration_s": 30,
                          "size_bytes": 20 * 1024 * 1024, "format": "mp4", "title": "ace"})
    assert ok["aspect"] == 1.78 and ok["title"] == "ace"           # aspect tagged, extra keys pass through
    assert H.accept_upload({"width": 1280, "height": 720, "duration_s": 5,
                            "size_bytes": 1024, "format": ".MOV"})["aspect"] == 1.78  # dot + case ok


@pytest.mark.parametrize("video,why", [
    ({"width": 1080, "height": 1920, "duration_s": 5, "size_bytes": 1024, "format": "mp4"}, "portrait"),
    ({"width": 1000, "height": 1000, "duration_s": 5, "size_bytes": 1024, "format": "mp4"}, "square"),
    ({"width": 0, "height": 1080, "duration_s": 5, "size_bytes": 1024, "format": "mp4"}, "no dimensions"),
    ({"width": 1920, "height": 1080, "duration_s": 5, "size_bytes": 1024, "format": "avi"}, "bad format"),
    ({"width": 1920, "height": 1080, "duration_s": 5,
      "size_bytes": (H.MAX_SIZE_MB + 50) * 1024 * 1024, "format": "mp4"}, "too big"),
    ({"width": 1920, "height": 1080, "duration_s": H.MAX_DURATION_S + 60,
      "size_bytes": 1024, "format": "mp4"}, "too long"),
])
def test_accept_upload_refuses_bad_clips(video, why):
    with pytest.raises(ValueError):
        H.accept_upload(video)


def test_rate_builds_a_vote_and_guards():
    assert H.rate("clip1", viewer=2, stars=4, owner=1) == {"highlight": "clip1", "viewer": 2, "stars": 4}
    for bad in (lambda: H.rate("clip1", 1, 5, owner=1),            # rating your own highlight
                lambda: H.rate("clip1", 2, 0, owner=1),            # below range
                lambda: H.rate("clip1", 2, 6, owner=1),            # above range
                lambda: H.rate("clip1", 2, True, owner=1),         # bool is not a star
                lambda: H.rate("clip1", 2, 3.5, owner=1)):         # not a whole star
        with pytest.raises(ValueError):
            bad()


def test_reputation_averages_only_this_clip():
    votes = [{"highlight": "a", "viewer": 2, "stars": 5},
             {"highlight": "a", "viewer": 3, "stars": 4},
             {"highlight": "a", "viewer": 4, "stars": 3},
             {"highlight": "b", "viewer": 2, "stars": 1}]          # another clip — must not bleed in
    assert H.reputation(votes, "a") == {"stars": 4.0, "votes": 3}
    assert H.reputation(votes, "zzz") == {"stars": 0.0, "votes": 0}  # unrated clip, not an error


@pytest.mark.parametrize("stars,votes,tier", [
    (4.6, 10, H.GOLD), (4.5, 10, H.GOLD),
    (4.4, 10, H.SILVER), (4.0, 5, H.SILVER),
    (3.9, 5, H.BRONZE), (3.5, 3, H.BRONZE),
    (3.4, 3, H.NONE), (2.0, 20, H.NONE),
    (5.0, 9, H.SILVER),        # perfect average but under 10 votes -> not gold yet (the votes floor)
    (5.0, 2, H.NONE),          # one/two rave votes earn nothing — the point of the floor
])
def test_laurels_are_earned_over_a_votes_floor(stars, votes, tier):
    assert H.laurel({"stars": stars, "votes": votes}) == tier


def test_card_joins_reputation_and_laurel():
    votes = [{"highlight": "a", "viewer": 2, "stars": 5},
             {"highlight": "a", "viewer": 3, "stars": 4},
             {"highlight": "a", "viewer": 4, "stars": 3}]          # 4.0 avg, 3 votes -> bronze
    assert H.card(votes, "a") == {"stars": 4.0, "votes": 3, "laurel": H.BRONZE}
    assert H.card(votes, "zzz") == {"stars": 0.0, "votes": 0, "laurel": H.NONE}
