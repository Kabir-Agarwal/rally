"""Messenger + basic AI helper (SPEC Y3 — ADD messenger + basic AI helper).

Proves the engine the messenger feature-block is built on: DM conversations keyed like a connection,
chronological threads, an unread/read model + inbox conversation-list, and the basic AI helper — a
deterministic keyword smart-reply (no LLM: "advanced messenger AI" is v2/OUT, and the money wall
forbids a paid model).
"""
import pytest

import messenger as M


def test_check_holds():
    assert M.check() is True                                       # the real engine self-check


def test_compose_builds_canonical_message_and_guards():
    m = M.compose(3, 2, "  hi  ", "t1")
    assert m == {"pair": (2, 3), "sender": 3, "body": "hi", "at": "t1", "read": False}
    for bad in (lambda: M.compose(1, 1, "hi", "t1"),               # to yourself
                lambda: M.compose(1, 2, "   ", "t1"),              # whitespace-only
                lambda: M.compose(1, 2, "", "t1"),                 # empty
                lambda: M.compose(1, 2, "hi", None)):              # no timestamp
        with pytest.raises(ValueError):
            bad()


def test_thread_is_chronological_and_isolated():
    msgs = [
        {"pair": (1, 2), "sender": 2, "body": "second", "at": "t2", "read": False},
        {"pair": (1, 2), "sender": 1, "body": "first",  "at": "t1", "read": True},
        {"pair": (1, 3), "sender": 3, "body": "other",  "at": "t1", "read": False},
    ]
    assert [m["body"] for m in M.thread(msgs, 1, 2)] == ["first", "second"]
    assert all(m["pair"] == (1, 2) for m in M.thread(msgs, 1, 2))


def test_unread_and_mark_read_are_scoped_and_pure():
    box = [
        {"pair": (1, 2), "sender": 2, "body": "yo",  "at": "t1", "read": False},
        {"pair": (1, 2), "sender": 2, "body": "hi",  "at": "t2", "read": False},
        {"pair": (1, 2), "sender": 1, "body": "hey", "at": "t3", "read": False},   # from me
        {"pair": (1, 3), "sender": 3, "body": "sup", "at": "t1", "read": False},
    ]
    assert M.unread_count(box, 1, 2) == 2
    assert M.unread_count(box, 1) == 3                             # both convos, not my own message
    cleared = M.mark_read(box, 1, 2)
    assert M.unread_count(cleared, 1, 2) == 0
    assert M.unread_count(cleared, 1) == 1                        # (1,3) untouched
    assert M.unread_count(box, 1) == 3                           # input not mutated (pure)


def test_inbox_lists_conversations_newest_first():
    box = [
        {"pair": (1, 2), "sender": 2, "body": "yo",  "at": "t1", "read": False},
        {"pair": (1, 2), "sender": 1, "body": "hey", "at": "t3", "read": False},
        {"pair": (1, 3), "sender": 3, "body": "sup", "at": "t2", "read": False},
    ]
    rows = M.inbox(box, 1)
    assert [r["with"] for r in rows] == [2, 3]                     # (1,2) last at t3 newer than (1,3) at t2
    assert rows[0]["last"]["body"] == "hey" and rows[0]["unread"] == 1
    assert M.inbox(box, 9) == []


@pytest.mark.parametrize("body,intent", [
    ("Want to play this week?", M.INVITE),
    ("How about Sunday at 10am?", M.TIME),
    ("thanks for the game", M.THANKS),        # THANKS beats the "game" invite word
    ("play tomorrow?", M.TIME),               # TIME beats INVITE when a day is named
    ("hey!", M.GREETING),
    ("are you free?", M.QUESTION),
    ("ok cool", M.GENERAL),
    ("they went home", M.GENERAL),            # whole-word: 'hey' not inside 'they'
])
def test_classify_intents(body, intent):
    assert M.classify(body) == intent


def test_suggest_replies_reacts_to_last_incoming_else_opens():
    conv = [{"pair": (1, 2), "sender": 2, "body": "fancy a hit tomorrow?", "at": "t1", "read": False}]
    assert M.suggest_replies(conv, 1, 2) == M.REPLIES[M.TIME]      # reply to their intent
    mine_last = conv + [{"pair": (1, 2), "sender": 1, "body": "sure", "at": "t2", "read": False}]
    assert M.suggest_replies(mine_last, 1, 2) == M.OPENERS         # my turn -> openers
    assert M.suggest_replies([], 1, 2) == M.OPENERS                # empty thread -> openers
    assert M.suggest_replies(conv, 1, 2) is not M.REPLIES[M.TIME]  # fresh list, not the shared constant
