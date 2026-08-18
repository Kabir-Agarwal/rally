"""Posts feed + followed players' matches (SPEC Y3).

Y3 ADD: posts feed + followed players' matches. Three pure halves:

  follow    — you FOLLOW a player. Following is DIRECTED and asymmetric: I follow you does not mean
              you follow me (that's the whole difference from Connect). So a follow is keyed by the
              ORDERED pair (follower, followee) — deliberately NOT nearby.pair_key's canonical a<b
              (the friendships shape a connection / a DM uses). A -> B and B -> A are two distinct
              edges that can both exist (a mutual follow), which a canonical pair could never store.
              follow() builds one edge (refusing self + a duplicate in that direction); following()
              is who I follow (the people whose content fills my feed), followers() is who follows me
              (the count on a profile), is_following() is the one bit the Follow / Following button reads.
  posts     — a player writes a POST (a bit of text). post() is the trust boundary — the body arrives
              from a user — so it refuses an empty/whitespace body and demands a timestamp to order by,
              exactly like messenger.compose. A post is {"author", "body", "at"}.
  the feed  — the one call the screen makes: merge into a single reverse-chronological timeline (a) the
              posts and (b) the MATCHES of everyone I follow — and my own — each row tagged with its
              "kind" so the UI can render a post card vs a match result. This is the two data sources
              joined the way nearby.discover() / competitions.hub() tie their engines together.

This is the pure ENGINE the feed feature-block is built on — DB-free and dependency-free, the same
shape as tournaments.py / leagues.py / practice.py / competitions.py / nearby.py / messenger.py /
highlights.py. Persistence is deferred on purpose: the follows table (follower, followee — unique in
that direction) and the posts table (author, body, at) land with the batched migrations (item #19,
SPEC Y5 — no session applies schema); the compose box, the follow button and the merged timeline land
on the UI. So the Feed screen lands as dummy UI now (SPEC Y1, blocks.py: feed off -> dummy) with this
engine proven and preflight-gated behind it. Followed players' MATCHES reuse the app's existing match
rows (side1/side2 players, a timestamp) — no new match model, the feed just surfaces them.

Privacy/permission are the public layer's job (item #16 — block/report, 16+ gate, who-may-see-whom).
The engine enforces only what feed content cannot exist without: a follow is directed and non-self,
a post has a body and a timestamp, and a feed row needs an `at` to sit on the timeline. Block/report
and private-account gating layer on at serve-time (item #16) without touching this engine.

Model — plain dicts, no DB (ids are anything hashable+comparable — the app's player ids are ints):
  follow  — {"follower", "followee"}. DIRECTED: follower follows followee. Unique per direction.
  post    — {"author", "body", "at"}. at = any sortable timestamp the caller stamps (the engine
            orders by it, never invents one — no clock in a pure engine).
  match   — the app's existing match dict: participants in "side1"/"side2" (lists), and an "at"
            timestamp the caller maps from the match's played-at. A match with no "at" (e.g. a live,
            unfinished one) is skipped — it can't be placed on a timeline.

feed() audience is "the people I follow, and me" — every feed shows your own activity too; the new
capability the spec names is followed players' matches. Each returned row is a COPY tagged with "kind"
(never the caller's dict), newest first, optionally capped to `limit`.

check() proves the directed follow graph (incl. a mutual follow both canonical-pair shapes can't),
the post trust guards, participant extraction, and the merged timeline (audience filter, match
surfacing, newest-first order, tagging, limit, purity) — same fail-loud shape as the sibling engines,
wired into deploy.py preflight.
"""

# --- feed row kinds (the UI renders a post card vs a match result off this) -------------------
POST = "post"
MATCH = "match"
KINDS = (POST, MATCH)


# --- follow graph (directed) -----------------------------------------------------------------
def follow(follower, followee, edges):
    """`follower` follows `followee`. Returns a NEW directed edge (the caller persists it); `edges` is
    untouched. Fails loud on following yourself, or a duplicate IN THIS DIRECTION — the (follower,
    followee) pair is unique, so a repeat is a bug to surface, not a silent no-op. The reverse edge
    (followee -> follower) is a different follow and is allowed to coexist (a mutual follow)."""
    if follower == followee:
        raise ValueError("cannot follow yourself")
    if any(e["follower"] == follower and e["followee"] == followee for e in edges):
        raise ValueError(f"{follower!r} already follows {followee!r}")
    return {"follower": follower, "followee": followee}


def is_following(me, them, edges):
    """True if `me` follows `them` — the bit the Follow / Following button reads. Directional: this is
    not symmetric, so is_following(a, b) and is_following(b, a) are independent."""
    return any(e["follower"] == me and e["followee"] == them for e in edges)


def following(me, edges):
    """The set of players `me` follows — the people whose posts and matches fill my feed."""
    return {e["followee"] for e in edges if e["follower"] == me}


def followers(me, edges):
    """The set of players who follow `me` — the follower count on a profile (the reverse direction)."""
    return {e["follower"] for e in edges if e["followee"] == me}


# --- posts -----------------------------------------------------------------------------------
def post(author, body, at):
    """Build a new post by `author` (the caller persists it). Trust-boundary guards: the body is
    non-empty (it arrives from a user — whitespace-only is rejected) and `at` is a real timestamp (a
    post with nothing to order it by can't sit on the timeline). The stored body is stripped."""
    text = (body or "").strip()
    if not text:
        raise ValueError("post body is empty")
    if at is None or at == "":
        raise ValueError("post needs a timestamp to order by")
    return {"author": author, "body": text, "at": at}


# --- followed players' matches ---------------------------------------------------------------
def players_of(match):
    """The participants of a match — its side1 + side2 players (the app's match shape). A feed surfaces
    a match when someone you follow is one of them. Missing sides read as empty (no participants)."""
    return list(match.get("side1") or []) + list(match.get("side2") or [])


# --- the feed (the join — the one call the screen makes) -------------------------------------
def feed(me, posts, matches, edges, limit=None):
    """`me`'s timeline: the posts and the matches of everyone I follow — and my own — merged newest
    first. Each row is a COPY tagged with "kind" (POST / MATCH) so the UI renders the right card; the
    caller's dicts are never mutated. `limit` caps the row count (None = all).

    Audience is following(me) plus me. A post is in when its author is in the audience. A match is in
    when any participant is — that's "followed players' matches", the spec's headline. A match with no
    "at" (a live/unfinished one) is skipped: it can't be placed on the timeline. Ordering is by `at`
    descending, stable for equal timestamps (posts before matches at the same instant)."""
    audience = following(me, edges) | {me}
    rows = [{**p, "kind": POST} for p in posts if p["author"] in audience]
    for m in matches:
        if m.get("at") in (None, ""):                       # no timestamp -> not on the timeline
            continue
        if audience.intersection(players_of(m)):            # a followed player (or me) played
            rows.append({**m, "kind": MATCH})
    rows.sort(key=lambda r: r["at"], reverse=True)          # newest first; stable reverse keeps ties
    return rows[:limit]


def check():
    """Fail loud (ValueError) if the feed engine regressed. Returns True when clean."""
    bad = []

    # 1. FOLLOW GRAPH IS DIRECTED — follow builds a (follower, followee) edge; refuses self + a
    #    same-direction duplicate; is_following is directional; and a MUTUAL follow (both directions)
    #    is two distinct edges that coexist — the thing a canonical a<b pair could never store.
    e = follow(1, 2, [])
    if e != {"follower": 1, "followee": 2}:
        bad.append(f"follow built the wrong edge: {e}")
    if not is_following(1, 2, [e]) or is_following(2, 1, [e]):   # 1->2 only; not the reverse
        bad.append("is_following is not directional")
    for op in (lambda: follow(1, 1, []),                        # self
               lambda: follow(1, 2, [e])):                      # duplicate, same direction
        try:
            op()
            bad.append("follow allowed a self/duplicate follow")
        except ValueError:
            pass
    mutual = [e, follow(2, 1, [e])]                             # 2->1 is a DIFFERENT edge, allowed
    if not (is_following(1, 2, mutual) and is_following(2, 1, mutual)):
        bad.append("a mutual follow (both directions) did not hold")
    net = [{"follower": 1, "followee": 2}, {"follower": 1, "followee": 3},
           {"follower": 4, "followee": 2}]
    if following(1, net) != {2, 3}:
        bad.append(f"following wrong: {following(1, net)}, want {{2, 3}}")
    if followers(2, net) != {1, 4}:
        bad.append(f"followers wrong: {followers(2, net)}, want {{1, 4}}")
    if following(9, net) != set() or followers(9, net) != set():
        bad.append("a stranger should follow / be followed by nobody")

    # 2. POST TRUST GUARDS — a post needs a non-empty body and a timestamp; the body is stripped.
    p = post(7, "  nice match!  ", "t5")
    if p != {"author": 7, "body": "nice match!", "at": "t5"}:
        bad.append(f"post built the wrong row: {p}")
    for op in (lambda: post(7, "   ", "t1"),                    # whitespace-only body
               lambda: post(7, "", "t1"),                      # empty body
               lambda: post(7, "hi", None),                    # no timestamp
               lambda: post(7, "hi", "")):                     # blank timestamp
        try:
            op()
            bad.append("post accepted an invalid post")
        except ValueError:
            pass

    # 3. PARTICIPANTS — side1 + side2; missing sides are empty (no participants to match on).
    if sorted(players_of({"side1": [1], "side2": [2, 3]})) != [1, 2, 3]:
        bad.append("players_of did not union both sides")
    if players_of({}) != []:
        bad.append("a match with no sides should have no participants")

    # 4. THE FEED JOIN — me(1) follows 2 and 3, not 4. My timeline = posts + matches of {1, 2, 3},
    #    newest first, each tagged; a stranger's (4) content is excluded; a live match (no at) is
    #    skipped; and the caller's dicts are not mutated.
    edges = [{"follower": 1, "followee": 2}, {"follower": 1, "followee": 3}]
    posts = [
        {"author": 2, "body": "followed post", "at": "t3"},    # followed -> in
        {"author": 1, "body": "my own post",   "at": "t5"},    # me       -> in (own activity shows)
        {"author": 4, "body": "stranger post", "at": "t9"},    # not followed -> OUT (even though newest)
    ]
    matches = [
        {"id": "m1", "side1": [3], "side2": [8], "at": "t4"},   # 3 is followed -> in
        {"id": "m2", "side1": [5], "side2": [6], "at": "t8"},   # neither followed -> OUT
        {"id": "m3", "side1": [1], "side2": [7], "at": "t2"},   # me played -> in
        {"id": "m4", "side1": [2], "side2": [9]},               # followed but LIVE (no at) -> skipped
    ]
    rows = feed(1, posts, matches, edges)
    got = [(r["kind"], r.get("author", r.get("id")), r["at"]) for r in rows]
    want = [(POST, 1, "t5"), (MATCH, "m1", "t4"), (POST, 2, "t3"), (MATCH, "m3", "t2")]
    if got != want:                                            # newest-first, stranger + live excluded
        bad.append(f"feed timeline wrong:\n    got  {got}\n    want {want}")
    if any(r["author"] == 4 for r in rows if r["kind"] == POST):
        bad.append("feed leaked a non-followed stranger's post")
    if any(r.get("id") == "m2" for r in rows):
        bad.append("feed leaked a match with no followed participant")
    if "kind" in posts[0] or "kind" in matches[0]:             # tagging must not mutate the inputs
        bad.append("feed mutated the caller's post/match dicts (must copy)")

    # 5. LIMIT + EMPTY — limit caps to the newest N; a user who follows nobody still sees only their
    #    own activity; and nothing to show is an empty timeline, not an error.
    if [r["at"] for r in feed(1, posts, matches, edges, limit=2)] != ["t5", "t4"]:
        bad.append("feed limit did not cap to the newest N")
    solo = feed(1, [{"author": 5, "body": "x", "at": "t1"}], [{"side1": [5], "side2": [6], "at": "t2"}], [])
    if solo != []:                                             # follows nobody, none of it is mine
        bad.append("a follow-nobody feed should be empty (only my own activity, and there is none)")
    mine = feed(1, [{"author": 1, "body": "hi", "at": "t1"}], [], [])
    if [r["kind"] for r in mine] != [POST]:                    # ...but my own post still shows
        bad.append("my own activity should show even when I follow nobody")

    if bad:
        raise ValueError("feed engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"feed OK: directed follow graph, posts, and a newest-first timeline of kinds {KINDS} "
          f"(followed players' matches + posts, plus your own)")
