"""Posts feed + followed players' matches (SPEC Y3 — ADD posts feed + followed players' matches).

Proves the engine the feed feature-block is built on: the DIRECTED follow graph (following is
asymmetric — not the canonical friendships pair — so A->B and B->A coexist), the post trust guards,
and the merged timeline that surfaces the posts and the matches of everyone you follow (and yourself),
newest first, each row tagged with its kind.
"""
import pytest

import feed as F


def test_check_holds():
    assert F.check() is True                                       # the real engine self-check


def test_follow_is_directed_and_guards():
    e = F.follow(1, 2, [])
    assert e == {"follower": 1, "followee": 2}
    assert F.is_following(1, 2, [e]) and not F.is_following(2, 1, [e])   # directional
    for bad in (lambda: F.follow(1, 1, []),                        # self
                lambda: F.follow(1, 2, [e])):                      # duplicate, same direction
        with pytest.raises(ValueError):
            bad()


def test_mutual_follow_is_two_distinct_edges():
    e = F.follow(1, 2, [])
    edges = [e, F.follow(2, 1, [e])]                               # reverse is allowed to coexist
    assert F.is_following(1, 2, edges) and F.is_following(2, 1, edges)


def test_following_and_followers_are_reverse_directions():
    net = [{"follower": 1, "followee": 2}, {"follower": 1, "followee": 3},
           {"follower": 4, "followee": 2}]
    assert F.following(1, net) == {2, 3}
    assert F.followers(2, net) == {1, 4}
    assert F.following(9, net) == set() and F.followers(9, net) == set()


def test_post_strips_body_and_guards():
    assert F.post(7, "  nice match!  ", "t5") == {"author": 7, "body": "nice match!", "at": "t5"}
    for bad in (lambda: F.post(7, "   ", "t1"),                    # whitespace-only
                lambda: F.post(7, "", "t1"),                       # empty
                lambda: F.post(7, "hi", None),                    # no timestamp
                lambda: F.post(7, "hi", "")):                     # blank timestamp
        with pytest.raises(ValueError):
            bad()


def test_players_of_unions_both_sides():
    assert sorted(F.players_of({"side1": [1], "side2": [2, 3]})) == [1, 2, 3]
    assert F.players_of({}) == []


def test_feed_merges_followed_posts_and_matches_newest_first():
    edges = [{"follower": 1, "followee": 2}, {"follower": 1, "followee": 3}]
    posts = [
        {"author": 2, "body": "followed post", "at": "t3"},       # followed -> in
        {"author": 1, "body": "my own post",   "at": "t5"},       # me       -> in
        {"author": 4, "body": "stranger post", "at": "t9"},       # not followed -> OUT (though newest)
    ]
    matches = [
        {"id": "m1", "side1": [3], "side2": [8], "at": "t4"},      # 3 followed -> in
        {"id": "m2", "side1": [5], "side2": [6], "at": "t8"},      # neither followed -> OUT
        {"id": "m3", "side1": [1], "side2": [7], "at": "t2"},      # me played -> in
        {"id": "m4", "side1": [2], "side2": [9]},                  # followed but LIVE (no at) -> skipped
    ]
    rows = F.feed(1, posts, matches, edges)
    assert [(r["kind"], r.get("author", r.get("id")), r["at"]) for r in rows] == [
        (F.POST, 1, "t5"), (F.MATCH, "m1", "t4"), (F.POST, 2, "t3"), (F.MATCH, "m3", "t2")]
    assert "kind" not in posts[0] and "kind" not in matches[0]     # inputs not mutated (rows are copies)


def test_feed_limit_and_own_activity():
    edges = [{"follower": 1, "followee": 2}]
    posts = [{"author": 1, "body": "mine", "at": "t5"}, {"author": 2, "body": "theirs", "at": "t3"}]
    assert [r["at"] for r in F.feed(1, posts, [], edges, limit=1)] == ["t5"]   # newest N
    # follows nobody: none of a stranger's content shows, but my own still does
    assert F.feed(1, [{"author": 5, "body": "x", "at": "t1"}], [], []) == []
    assert [r["kind"] for r in F.feed(1, [{"author": 1, "body": "hi", "at": "t1"}], [], [])] == [F.POST]
