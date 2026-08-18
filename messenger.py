"""Messenger + a basic AI helper (SPEC Y3).

Y3 ADD: messenger + basic AI helper. Two halves, both pure:

  messenger   — direct messages between two players. A conversation is one unordered pair, keyed the
                SAME way a connection is (nearby.pair_key — the friendships shape), so "message"
                follows naturally from "Connect": the people you can DM are the people you paired with.
                compose() makes a message, thread() reads a conversation oldest-first, inbox() is the
                conversation-list screen (one row per person: who, last message, unread count, most-
                recent first), unread_count()/mark_read() drive the badge and the read receipts.
  AI helper   — a BASIC assistant: smart quick-replies. classify() reads the other player's last
                message into one small intent (invite / time / question / greeting / thanks / general)
                and suggest_replies() offers 2–3 ready-to-tap replies for it — the "smart reply" bar,
                the way a messenger's basic AI works. It is deliberately a keyword heuristic, NOT an
                LLM: the spec keeps "advanced messenger AI" for v2 (SPEC OUT), and the money wall
                forbids a paid model. So it costs nothing, is deterministic, and is fully testable.
                # ponytail: keyword heuristic; a real intent model / LLM is "advanced messenger AI" = v2/OUT.

This is the pure ENGINE the messenger feature-block is built on — DB-free and (bar reusing pair_key)
dependency-free, the same shape as tournaments.py / leagues.py / practice.py / competitions.py /
nearby.py. Persistence is deferred on purpose: the messages table (pair, sender, body, sent-at, read)
lands with the batched migrations (item #19, SPEC Y5 — no session applies schema); the thread/inbox
screens and the smart-reply bar land on the UI. So the Messages screen lands as dummy UI now (SPEC
Y1, blocks.py: messages off -> dummy) with this engine proven and preflight-gated behind it.

Privacy/permission are the public layer's job (item #16 — block/report, 16+ gate). The engine only
enforces what a message cannot exist without: a non-empty body, a real timestamp to order by, and you
cannot message yourself. Blocking a sender and gating DMs to accepted connections layer on top at
send-time (item #16) without touching this engine.

Model — plain dicts, no DB (ids are anything hashable+comparable — the app's player ids are ints):
  message — {"pair", "sender", "body", "at", "read": bool}. pair = pair_key(a, b) (a<b canonical,
            same as a connection). sender is one of the pair. at = any sortable timestamp the caller
            stamps (the engine orders by it, never invents one — no clock in a pure engine). read =
            whether the RECIPIENT has seen it (a message is unread only for its recipient).

check() proves the compose trust guards, chronological threads isolated per conversation, the
unread/read model, the inbox conversation-list, and the whole intent->replies helper — same fail-loud
shape as the sibling engines, wired into deploy.py preflight.
"""
import re

from nearby import pair_key   # a conversation is keyed exactly like a connection (friendships shape)

# --- AI-helper intents (SPEC Y3: basic AI helper) --------------------------------------------
INVITE   = "invite"     # they want to play — suggest picking a time
TIME     = "time"       # they proposed a day/time — suggest confirm / counter
QUESTION = "question"   # a plain question — suggest yes / no / check
GREETING = "greeting"   # hi/hey — suggest a greeting back
THANKS   = "thanks"     # gratitude — suggest you're welcome
GENERAL  = "general"    # anything else — safe neutral replies
INTENTS  = (INVITE, TIME, QUESTION, GREETING, THANKS, GENERAL)

# Keyword vocabularies for the heuristic. Checked in the priority order of classify() below.
_THANK_WORDS  = ("thanks", "thank you", "thankyou", "thx", "ty", "cheers", "appreciate")
_DAY_WORDS    = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                 "today", "tomorrow", "tonight", "morning", "afternoon", "evening", "weekend")
_INVITE_WORDS = ("play", "game", "match", "hit", "rally", "court", "practice", "knock",
                 "singles", "doubles")
_GREET_WORDS  = ("hi", "hey", "hello", "yo", "hiya", "sup")
# A clock time: "10am", "6 pm", "3:30", "10:30pm". Word-boundaried so "I am"/"9 games" don't trip it.
_CLOCK = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b|\b\d{1,2}:\d{2}\b")

# Ready-to-tap replies per intent, and openers when it's your turn to start / continue.
REPLIES = {
    INVITE:   ["Sure, when works? 🎾", "I'm in!", "Can't this week — next?"],
    TIME:     ["Works for me 👍", "Can we do a bit later?", "Let me check and confirm"],
    QUESTION: ["Yes", "No", "Let me check and get back to you"],
    GREETING: ["Hey! 👋", "Hi — up for a hit?"],
    THANKS:   ["Anytime! 🎾", "👍"],
    GENERAL:  ["👍", "Sounds good", "Let me get back to you"],
}
OPENERS = ["Hey! 👋", "Up for a hit this week? 🎾", "Good game earlier!"]


def _has_word(text, words):
    """True if any of `words` appears in `text` as a whole word (so 'hey' misses 'they', 'ty' misses
    'party'). `text` is already lowercased."""
    return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)


def classify(body):
    """The tiny intent 'model': map a message body to one INTENT by keyword, in priority order.
    Gratitude and a concrete time win first (they are usually the point of the message), then an
    invite, a greeting, a bare question, else general. Empty/None -> general."""
    t = (body or "").strip().lower()
    if not t:
        return GENERAL
    if _has_word(t, _THANK_WORDS):
        return THANKS
    if _has_word(t, _DAY_WORDS) or _CLOCK.search(t):
        return TIME
    if _has_word(t, _INVITE_WORDS):
        return INVITE
    if _has_word(t, _GREET_WORDS):
        return GREETING
    if t.endswith("?"):
        return QUESTION
    return GENERAL


# --- messenger core --------------------------------------------------------------------------
def other(pair, me):
    """The counterpart in a conversation. Fails loud if `me` is not part of `pair` — you cannot have a
    conversation you are not in, so that's a caller bug to surface, not a silent None."""
    a, b = pair
    if me == a:
        return b
    if me == b:
        return a
    raise ValueError(f"{me!r} is not part of conversation {pair!r}")


def compose(me, them, body, at):
    """Build a new message from `me` to `them` (the caller persists it). Trust-boundary guards: the
    body is non-empty (a message arrives from a user — whitespace-only is rejected), you cannot
    message yourself, and `at` is a real timestamp (a message with nothing to order it by is a
    defect). The stored body is stripped of surrounding whitespace."""
    if me == them:
        raise ValueError("cannot message yourself")
    text = (body or "").strip()
    if not text:
        raise ValueError("message body is empty")
    if at is None or at == "":
        raise ValueError("message needs a timestamp to order by")
    return {"pair": pair_key(me, them), "sender": me, "body": text, "at": at, "read": False}


def thread(messages, me, them):
    """The conversation between `me` and `them`, oldest message first. Only that pair's messages (other
    conversations in `messages` are ignored); order is by `at`, stable for equal timestamps."""
    key = pair_key(me, them)
    return sorted((m for m in messages if m["pair"] == key), key=lambda m: m["at"])


def unread_count(messages, me, them=None):
    """How many messages `me` has not read: those addressed to me (sender is the other party) and not
    yet read. Scoped to one conversation when `them` is given, else across all of my conversations —
    the global badge. Messages I sent, and conversations I'm not in, never count."""
    key = pair_key(me, them) if them is not None else None
    return sum(1 for m in messages
               if me in m["pair"] and m["sender"] != me and not m["read"]
               and (key is None or m["pair"] == key))


def mark_read(messages, me, them=None):
    """Return a NEW list (the input is untouched — pure) with every message addressed to `me` marked
    read: the whole inbox, or one conversation when `them` is given. My own messages and messages in
    conversations I'm not in are copied through unchanged."""
    key = pair_key(me, them) if them is not None else None
    out = []
    for m in messages:
        mine_to_read = (me in m["pair"] and m["sender"] != me and not m["read"]
                        and (key is None or m["pair"] == key))
        out.append({**m, "read": True} if mine_to_read else dict(m))
    return out


def inbox(messages, me):
    """The conversation-list screen for `me`: one row per person I've messaged with, most-recent
    conversation first. Each row: {"pair", "with": other, "last": <newest message>, "unread": n}."""
    convos = {}
    for m in messages:
        if me in m["pair"]:
            convos.setdefault(m["pair"], []).append(m)
    rows = []
    for key, msgs in convos.items():
        msgs = sorted(msgs, key=lambda m: m["at"])
        rows.append({
            "pair": key,
            "with": other(key, me),
            "last": msgs[-1],
            "unread": sum(1 for m in msgs if m["sender"] != me and not m["read"]),
        })
    rows.sort(key=lambda r: r["last"]["at"], reverse=True)   # newest conversation on top
    return rows


def suggest_replies(messages, me, them):
    """The basic AI helper: 2–3 ready-to-tap replies for `me` in this conversation. If the other player
    spoke last, classify their message and suggest replies to it; if I spoke last (or the thread is
    empty), suggest an opener instead. Always returns a fresh list (safe for the caller to mutate)."""
    th = thread(messages, me, them)
    if th and th[-1]["sender"] != me:                # they spoke last -> reply to their intent
        return list(REPLIES[classify(th[-1]["body"])])
    return list(OPENERS)                             # my turn / fresh thread -> an opener


def check():
    """Fail loud (ValueError) if the messenger engine or the basic AI helper regressed. True when clean."""
    bad = []

    # 1. COMPOSE TRUST GUARDS — a message needs a non-empty body, a timestamp, and two different people.
    #    A good compose builds the canonical-pair message, unread, body stripped.
    m = compose(1, 2, "  hi there  ", "t1")
    if m != {"pair": (1, 2), "sender": 1, "body": "hi there", "at": "t1", "read": False}:
        bad.append(f"compose built the wrong message: {m}")
    if compose(3, 2, "hey", "t1")["pair"] != (2, 3):   # pair is canonical regardless of arg order
        bad.append("compose did not canonicalise the pair")
    for op in (lambda: compose(1, 1, "hi", "t1"),      # to yourself
               lambda: compose(1, 2, "   ", "t1"),     # whitespace-only body
               lambda: compose(1, 2, "", "t1"),        # empty body
               lambda: compose(1, 2, "hi", None)):     # no timestamp
        try:
            op()
            bad.append("compose accepted an invalid message")
        except ValueError:
            pass

    # 2. THREAD — oldest first, only this pair's messages, other conversations ignored.
    msgs = [
        {"pair": (1, 2), "sender": 2, "body": "second", "at": "t2", "read": False},
        {"pair": (1, 2), "sender": 1, "body": "first",  "at": "t1", "read": True},
        {"pair": (1, 3), "sender": 3, "body": "elsewhere", "at": "t1", "read": False},
    ]
    th = thread(msgs, 1, 2)
    if [x["body"] for x in th] != ["first", "second"]:
        bad.append(f"thread order/isolation wrong: {[x['body'] for x in th]}")
    if any(x["pair"] == (1, 3) for x in th):
        bad.append("thread leaked another conversation")

    # 3. UNREAD + MARK_READ — count only messages TO me, unread; per-thread and global; mark_read is
    #    pure (input untouched) and drives the count to zero for that thread only.
    box = [
        {"pair": (1, 2), "sender": 2, "body": "yo",   "at": "t1", "read": False},  # to me(1), unread
        {"pair": (1, 2), "sender": 2, "body": "hi",   "at": "t2", "read": False},  # to me(1), unread
        {"pair": (1, 2), "sender": 1, "body": "hey",  "at": "t3", "read": False},  # from me -> not counted
        {"pair": (1, 3), "sender": 3, "body": "sup",  "at": "t1", "read": False},  # other convo, to me
        {"pair": (4, 5), "sender": 4, "body": "none", "at": "t1", "read": False},  # not my convo at all
    ]
    if unread_count(box, 1, 2) != 2:
        bad.append(f"per-thread unread wrong: {unread_count(box, 1, 2)}, want 2")
    if unread_count(box, 1) != 3:                       # 2 in convo (1,2) + 1 in (1,3); not (4,5)
        bad.append(f"global unread wrong: {unread_count(box, 1)}, want 3")
    read12 = mark_read(box, 1, 2)
    if unread_count(read12, 1, 2) != 0:
        bad.append("mark_read did not clear the thread's unread")
    if unread_count(read12, 1) != 1:                    # (1,3) still unread
        bad.append("mark_read cleared more than the named thread")
    if unread_count(box, 1) != 3:
        bad.append("mark_read mutated the caller's messages (must be pure)")
    if unread_count(mark_read(box, 1), 1) != 0:         # mark all my convos read
        bad.append("global mark_read did not clear everything addressed to me")

    # 4. INBOX — one row per conversation, right counterpart + last message + unread, newest first.
    rows = inbox(box, 1)
    if [r["with"] for r in rows] != [2, 3]:             # convo (1,2) last at t3 is newer than (1,3) at t1
        bad.append(f"inbox order/counterparts wrong: {[r['with'] for r in rows]}")
    top = rows[0]
    if top["last"]["body"] != "hey" or top["unread"] != 2:
        bad.append(f"inbox top row wrong: last={top['last']['body']!r} unread={top['unread']}")
    if inbox(box, 9) != []:                             # someone with no conversations
        bad.append("inbox invented a conversation for a stranger")

    # 5. CLASSIFY — each intent from a representative message; priority collisions; whole-word matching.
    for body, want in [
        ("Want to play this week?",        INVITE),
        ("How about Sunday at 10am?",       TIME),
        ("thanks for the game 🎾",          THANKS),   # THANKS beats the invite word "game"
        ("play tomorrow?",                  TIME),      # TIME beats INVITE when a day is named
        ("hey!",                            GREETING),
        ("are you free?",                   QUESTION),
        ("ok cool",                         GENERAL),
        ("",                                GENERAL),
        ("they went home",                  GENERAL),   # 'hey' must not match inside 'they'
    ]:
        if classify(body) != want:
            bad.append(f"classify({body!r}) = {classify(body)!r}, want {want!r}")

    # 6. SUGGEST_REPLIES — reply to the OTHER player's last message; opener when it's my turn / empty.
    conv = [{"pair": (1, 2), "sender": 2, "body": "fancy a hit tomorrow?", "at": "t1", "read": False}]
    if suggest_replies(conv, 1, 2) != REPLIES[TIME]:    # they asked, with a day -> TIME replies
        bad.append(f"suggest_replies ignored the incoming intent: {suggest_replies(conv, 1, 2)}")
    conv2 = conv + [{"pair": (1, 2), "sender": 1, "body": "sure!", "at": "t2", "read": False}]
    if suggest_replies(conv2, 1, 2) != OPENERS:         # I spoke last -> openers
        bad.append("suggest_replies did not fall back to openers when I spoke last")
    if suggest_replies([], 1, 2) != OPENERS:            # empty thread -> openers
        bad.append("suggest_replies did not offer openers on an empty thread")
    if suggest_replies(conv, 1, 2) is REPLIES[TIME]:    # must be a fresh list, not the shared constant
        bad.append("suggest_replies returned the shared REPLIES list (caller could mutate it)")

    if bad:
        raise ValueError("messenger engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"messenger OK: DM threads + inbox, unread/read model, basic AI helper intents {INTENTS}")
