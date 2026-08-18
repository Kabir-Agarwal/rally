"""Feature-block registry — the single source of truth for prod-safe, block-by-block delivery (SPEC Y1).

Y1: the app is LIVE and prod never breaks. New features land one block at a time, and a new
screen shows as *dummy UI* (a "Coming soon" placeholder) before it is wired. That staging lives
here, in one field per block, instead of scattered across templates and JS:

  off   — declared but invisible: no nav tab, its /<id> URL 404s. The default for planned work.
  dummy — visible placeholder: a nav tab + a "Coming soon" panel, no real logic yet.
  live  — fully wired and shipped.

Delivering a feature is just walking its block off -> dummy -> live across its own queue item.
Because a half-built block can only ever be `dummy` (a harmless placeholder) until its item is
done, prod keeps working the whole way. `validate()` (run in deploy.py preflight) refuses a
deploy whose registry is inconsistent, so "prod never breaks" is enforced, not hoped for.

id must match the SPA tab id (app.js TAB_URL / shell.html nav). label/icon show in the nav tab.
"""

STATES = ("off", "dummy", "live")

# The five shipped tabs are hard-wired in shell.html + app.js; they are listed here as the live
# baseline so validate() catches anyone accidentally turning a shipped tab off/dummy. The planned
# Y3 screens are pre-declared `off` — each lands via its own queue item by flipping off->dummy->live.
REGISTRY = [
    {"id": "live",         "label": "Live",        "icon": "\U0001F3BE", "state": "live"},
    {"id": "leaderboard",  "label": "Ranks",       "icon": "\U0001F3C6", "state": "live"},
    {"id": "log",          "label": "Create Game", "icon": "✏️", "state": "live"},
    {"id": "groups",       "label": "Groups",      "icon": "\U0001F465", "state": "live"},
    {"id": "history",      "label": "Profile",     "icon": "\U0001F464", "state": "live"},
    # --- planned (SPEC Y3), landing block by block ---
    {"id": "tournaments",  "label": "Tournaments", "icon": "\U0001F3C6", "state": "off"},
    {"id": "leagues",      "label": "Leagues",     "icon": "\U0001F3BD", "state": "off"},
    {"id": "competitions", "label": "Compete",     "icon": "⚔️", "state": "off"},
    {"id": "nearby",       "label": "Nearby",      "icon": "\U0001F4CD", "state": "off"},
    {"id": "messages",     "label": "Messages",    "icon": "\U0001F4AC", "state": "off"},
    {"id": "highlights",   "label": "Highlights",  "icon": "\U0001F3AC", "state": "off"},
    {"id": "feed",         "label": "Feed",        "icon": "\U0001F4F0", "state": "off"},
    {"id": "orgs",         "label": "Clubs",       "icon": "\U0001F3E2", "state": "off"},
]

CORE = ("live", "leaderboard", "log", "groups", "history")


def dummy_blocks():
    """Blocks currently landing as placeholder UI — what shell.html/app.js render as a dummy tab."""
    return [b for b in REGISTRY if b["state"] == "dummy"]


def validate():
    """Fail loud on an inconsistent registry (called in deploy.py preflight). Returns True clean."""
    ids = [b["id"] for b in REGISTRY]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate block ids: {dupes}")
    for b in REGISTRY:
        if not b.get("id") or not b.get("label"):
            raise ValueError(f"block missing id/label: {b!r}")
        if b.get("state") not in STATES:
            raise ValueError(f"block {b.get('id')!r}: bad state {b.get('state')!r} (want {STATES})")
    not_live = [c for c in CORE if next(b for b in REGISTRY if b["id"] == c)["state"] != "live"]
    if not_live:
        raise ValueError(f"shipped tabs must stay live: {not_live}")
    return True


if __name__ == "__main__":
    validate()
    print("blocks OK:", ", ".join(f"{b['id']}={b['state']}" for b in REGISTRY))
