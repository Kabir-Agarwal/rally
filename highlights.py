"""Highlights — landscape video upload + reputation stars + laurels (SPEC Y3).

Y3 ADD: highlights (landscape video upload, reputation stars, laurels). One clip, three pure halves:

  landscape upload — the gate a video clears to become a highlight. A highlight is LANDSCAPE (the spec
                     word): a clip filmed wide, not a portrait phone video, so it plays full-bleed and
                     ties to the Y6 video tool's landscape court framing. accept_upload() is the trust
                     boundary — the file arrives from a user — and refuses portrait/square, an unknown
                     format, an oversized file, or an over-long clip, each with the reason to show.
  reputation stars — viewers rate a highlight 1–5 stars; the clip's reputation is the average + the
                     vote count. rate() builds one vote (the DB's unique (highlight, viewer) key makes
                     it one-vote-per-viewer, an upsert — the friendships-pair shape) and refuses rating
                     your OWN highlight; reputation() aggregates. This is the "content sharing with
                     reputation" the item-0 study mapped here (feature #8).
  laurels          — the earned award a highlight wins from its reputation: film-festival wreaths,
                     none -> bronze -> silver -> gold. A votes FLOOR gates each tier so one 5-star vote
                     can't mint gold — the laurel is EARNED and credible, the same "earned-from-0" /
                     rating-credibility principle the rest of Rally holds to. laurel() maps a
                     reputation to its tier; card() joins stars+laurel — the one call the screen makes
                     per clip, the way nearby.discover() / competitions.hub() tie their halves together.

This is the pure ENGINE the highlights feature-block is built on — DB-free and dependency-free, the
same shape as tournaments.py / leagues.py / practice.py / competitions.py / nearby.py / messenger.py.
Persistence is deferred on purpose: the highlights table (clip, owner, url, dims, laurel) and the
ratings table (highlight, viewer, stars — unique per pair) land with the batched migrations (item #19,
SPEC Y5 — no session applies schema); the upload form, the video player, the star bar and the laurel
badge land on the UI. So the Highlights screen lands as dummy UI now (SPEC Y1, blocks.py: highlights
off -> dummy) with this engine proven and preflight-gated behind it.

The actual video *processing* (rally segmentation, highlight-reel generation, heatmaps) is the Y6 tool
— laptop-only, LAST, owner ruling — and only ever uploads finished clips + stats JSON. This engine is
the upload/reputation layer those clips land in, not the vision work.
  # ponytail: metadata gate only (dims/format/size/duration the caller reads off the file). Decoding
  # the pixels to verify orientation is the Y6 laptop-only vision tool's job, not a web upload path.

Privacy/permission are the public layer's job (item #16 — block/report, 16+ gate). The engine enforces
only what a highlight cannot exist without: a landscape clip within limits, a star in 1–5, and you
cannot rate your own clip. Block/report and who-may-view layer on top at serve-time without touching it.

Model — plain dicts, no DB (ids are anything hashable+comparable — the app's player/clip ids are ints):
  video   — {"width", "height", "duration_s", "size_bytes", "format", ...}; other keys (title, url…)
            pass through accept_upload untouched. accept_upload adds "aspect" (w/h, 2dp) on success.
  rating  — {"highlight", "viewer", "stars"}; stars an int 1–5. One row per (highlight, viewer).

check() proves the landscape gate (accept + every rejection reason), the star trust guards, the
reputation average, and the laurel tiers incl. the votes floor + the joined card() — same fail-loud
shape as the sibling engines, wired into deploy.py preflight.
"""

# --- landscape upload gate (SPEC Y3: landscape video upload) ---------------------------------
ALLOWED_FORMATS = ("mp4", "mov", "webm")   # the web-playable container set; case-insensitive, dot ok
MAX_SIZE_MB = 200                          # a highlight is a short clip, not a full match (free-tier egress)
MAX_DURATION_S = 120                       # 2 minutes — a highlight reel, not the whole game

# --- reputation stars (SPEC Y3: reputation stars) --------------------------------------------
MIN_STARS, MAX_STARS = 1, 5

# --- laurels (SPEC Y3: laurels) --------------------------------------------------------------
NONE, BRONZE, SILVER, GOLD = "none", "bronze", "silver", "gold"
LAURELS = (NONE, BRONZE, SILVER, GOLD)
# (tier, min average stars, min votes). Ordered best-first; first match wins. The vote floor is the
# point: a laurel is EARNED — one glowing vote is not a gold clip. Checked highest tier down.
LAUREL_TIERS = ((GOLD, 4.5, 10), (SILVER, 4.0, 5), (BRONZE, 3.5, 3))


def _pos_num(x):
    """A real, positive number — the dimensions/size/duration a real video file has. Rejects None,
    strings and bool (a file's width is never True)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


def accept_upload(video):
    """Validate a video upload as a landscape highlight clip; return it normalised (with "aspect") or
    raise ValueError with the reason to show the uploader. This is a trust boundary — the file's
    metadata arrives from the user — so every field is checked, headline rule first: LANDSCAPE.

    Refuses, each with its own message: no valid dimensions; not landscape (width must exceed height —
    portrait and square are out); an unsupported container; a file over MAX_SIZE_MB; a clip over
    MAX_DURATION_S. Extra keys on `video` (title, url, owner…) pass through untouched."""
    w, h = video.get("width"), video.get("height")
    if not (_pos_num(w) and _pos_num(h)):
        raise ValueError(f"video has no valid dimensions (got {w!r}x{h!r})")
    if w <= h:                                     # landscape = wider than tall; square/portrait rejected
        raise ValueError(f"video must be landscape — width must exceed height (got {w}x{h})")
    fmt = str(video.get("format", "")).lower().lstrip(".")
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"unsupported format {video.get('format')!r} "
                         f"(allowed: {', '.join(ALLOWED_FORMATS)})")
    size = video.get("size_bytes")
    if not _pos_num(size):
        raise ValueError(f"video has no valid size (got {size!r})")
    mb = size / (1024 * 1024)
    if mb > MAX_SIZE_MB:
        raise ValueError(f"video is {mb:.0f} MB, over the {MAX_SIZE_MB} MB highlight limit")
    dur = video.get("duration_s")
    if not _pos_num(dur):
        raise ValueError(f"video has no valid duration (got {dur!r})")
    if dur > MAX_DURATION_S:
        raise ValueError(f"clip is {dur:.0f}s, over the {MAX_DURATION_S}s highlight limit")
    return {**video, "aspect": round(w / h, 2)}


def _stars_ok(stars):
    """A star vote is a whole 1–5. Rejects None/floats/strings and bool (True is not a 1-star vote)."""
    return isinstance(stars, int) and not isinstance(stars, bool) and MIN_STARS <= stars <= MAX_STARS


def rate(highlight, viewer, stars, owner):
    """Build one star vote (the caller persists it; the DB's unique (highlight, viewer) makes re-rating
    an upsert — one vote per viewer, the friendships-pair shape). Trust guards: you cannot rate your
    OWN highlight, and `stars` is a whole 1–5. Fails loud otherwise — both are caller bugs to surface."""
    if viewer == owner:
        raise ValueError("cannot rate your own highlight")
    if not _stars_ok(stars):
        raise ValueError(f"stars must be a whole number {MIN_STARS}–{MAX_STARS}, got {stars!r}")
    return {"highlight": highlight, "viewer": viewer, "stars": stars}


def reputation(ratings, highlight):
    """A highlight's reputation from its star votes: {"stars": average (1dp), "votes": n}. Only this
    highlight's votes count; no votes -> {"stars": 0.0, "votes": 0} (an unrated clip, not an error)."""
    votes = [r["stars"] for r in ratings if r["highlight"] == highlight]
    if not votes:
        return {"stars": 0.0, "votes": 0}
    return {"stars": round(sum(votes) / len(votes), 1), "votes": len(votes)}


def laurel(rep):
    """The laurel a reputation has earned: 'none' | 'bronze' | 'silver' | 'gold'. Highest tier whose
    average-stars AND votes floor are both met — the floor is why a single rave vote earns nothing."""
    for tier, min_stars, min_votes in LAUREL_TIERS:
        if rep["votes"] >= min_votes and rep["stars"] >= min_stars:
            return tier
    return NONE


def card(ratings, highlight):
    """The one call the Highlights screen makes per clip: its reputation joined with its laurel —
    {"stars", "votes", "laurel"}. The two halves tied together, the way nearby.discover() joins its."""
    rep = reputation(ratings, highlight)
    return {**rep, "laurel": laurel(rep)}


def check():
    """Fail loud (ValueError) if the highlights engine regressed. Returns True when clean."""
    bad = []

    # 1. LANDSCAPE UPLOAD GATE — a wide clip within limits is accepted (and tagged with its aspect);
    #    portrait/square, an unknown format, an oversized file and an over-long clip are each refused.
    ok = accept_upload({"width": 1920, "height": 1080, "duration_s": 30,
                        "size_bytes": 20 * 1024 * 1024, "format": "mp4", "title": "ace"})
    if ok.get("aspect") != 1.78 or ok.get("title") != "ace":     # aspect tagged, extra keys pass through
        bad.append(f"accept_upload mangled a good clip: {ok}")
    if accept_upload({"width": 1280, "height": 720, "duration_s": 5,
                     "size_bytes": 1024, "format": ".MOV"})["aspect"] != 1.78:  # dot + case tolerated
        bad.append("accept_upload rejected a valid .MOV / uppercase format")
    for vid, why in [
        ({"width": 1080, "height": 1920, "duration_s": 5, "size_bytes": 1024, "format": "mp4"}, "portrait"),
        ({"width": 1000, "height": 1000, "duration_s": 5, "size_bytes": 1024, "format": "mp4"}, "square"),
        ({"width": 0, "height": 1080, "duration_s": 5, "size_bytes": 1024, "format": "mp4"}, "no dims"),
        ({"width": 1920, "height": 1080, "duration_s": 5, "size_bytes": 1024, "format": "avi"}, "format"),
        ({"width": 1920, "height": 1080, "duration_s": 5,
          "size_bytes": (MAX_SIZE_MB + 50) * 1024 * 1024, "format": "mp4"}, "too big"),
        ({"width": 1920, "height": 1080, "duration_s": MAX_DURATION_S + 60,
          "size_bytes": 1024, "format": "mp4"}, "too long"),
    ]:
        try:
            accept_upload(vid)
            bad.append(f"accept_upload accepted a bad clip ({why})")
        except ValueError:
            pass

    # 2. REPUTATION STARS — rate builds a vote and guards self-rating + the 1–5 range; reputation is
    #    the average + count, and an unrated clip is 0/0 (not an error).
    r = rate("clip1", viewer=2, stars=4, owner=1)
    if r != {"highlight": "clip1", "viewer": 2, "stars": 4}:
        bad.append(f"rate built the wrong vote: {r}")
    for op in (lambda: rate("clip1", 1, 5, owner=1),   # rating your own highlight
               lambda: rate("clip1", 2, 0, owner=1),   # below range
               lambda: rate("clip1", 2, 6, owner=1),   # above range
               lambda: rate("clip1", 2, True, owner=1),  # bool is not a star
               lambda: rate("clip1", 2, 3.5, owner=1)):  # not a whole star
        try:
            op()
            bad.append("rate accepted an illegal vote")
        except ValueError:
            pass
    votes = [{"highlight": "a", "viewer": 2, "stars": 5},
             {"highlight": "a", "viewer": 3, "stars": 4},
             {"highlight": "a", "viewer": 4, "stars": 3},
             {"highlight": "b", "viewer": 2, "stars": 1}]   # another clip — must not bleed in
    rep = reputation(votes, "a")
    if rep != {"stars": 4.0, "votes": 3}:                     # (5+4+3)/3 = 4.0, three votes, b ignored
        bad.append(f"reputation wrong: {rep}, want stars 4.0 votes 3")
    if reputation(votes, "zzz") != {"stars": 0.0, "votes": 0}:
        bad.append("an unrated clip should be 0.0/0")

    # 3. LAURELS + card() — each tier at its floor; the votes floor blocks a high average on too few
    #    votes; and card() joins reputation with the laurel it earned.
    for stars, n, want in [
        (4.6, 10, GOLD), (4.5, 10, GOLD),
        (4.4, 10, SILVER), (4.0, 5, SILVER),
        (3.9, 5, BRONZE),  (3.5, 3, BRONZE),
        (3.4, 3, NONE), (2.0, 20, NONE),
        (5.0, 9, SILVER),                # perfect average but under 10 votes -> not gold yet (floor)
        (5.0, 2, NONE),                  # one/two rave votes earn NOTHING — the whole point of the floor
    ]:
        got = laurel({"stars": stars, "votes": n})
        if got != want:
            bad.append(f"laurel(stars={stars}, votes={n}) = {got!r}, want {want!r}")
    c = card(votes, "a")                                     # reputation 4.0/3 -> bronze (>=3.5, >=3)
    if c != {"stars": 4.0, "votes": 3, "laurel": BRONZE}:
        bad.append(f"card did not join reputation+laurel: {c}")
    if card(votes, "zzz") != {"stars": 0.0, "votes": 0, "laurel": NONE}:
        bad.append("an unrated clip's card should carry no laurel")

    if bad:
        raise ValueError("highlights engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"highlights OK: landscape gate ({'/'.join(ALLOWED_FORMATS)}, <={MAX_SIZE_MB}MB, "
          f"<={MAX_DURATION_S}s), {MIN_STARS}-{MAX_STARS}star reputation, laurels {LAURELS}")
