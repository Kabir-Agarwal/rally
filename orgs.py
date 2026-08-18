"""Org / club accounts (SPEC Y3).

Y3 ADD: org/club accounts. An *account* is more than a name — the substance the item-0 study names
is "org entity, roles": a club ≈ a group + an owner role. The existing `groups` table is a private
space keyed by a code with ONE scalar `admin_id`; an org/club account is a public identity with a
real membership ladder — who owns it, who may manage it, who merely belongs. That role model is the
irreducible core here, so this engine is exactly that: an account profile + a three-rung role graph
with one protected invariant — **an account always has exactly one owner.**

Two halves, both pure:

  profile  — account(name, handle, kind) is the trust boundary. The name arrives from a user (refuse
             empty/whitespace, like feed.post / messenger.compose), the public @handle is normalized
             and charset-checked (a club is addressed by it), and the kind is a club or an org. It
             returns only the validated profile — the caller stamps the id + created_at (no clock/id
             in a pure engine), exactly as feed.post / nearby leave persistence to the caller.
  roles    — a membership is {"org", "player", "role"} with role OWNER > ADMIN > MEMBER. found()
             seats the creator as the sole OWNER. add() lets a manager admit a MEMBER; set_role() is
             the owner granting/revoking ADMIN; remove() drops a member (self-leave, or a strictly-
             higher role removing a lower one); transfer() is the ONLY way OWNER moves — it swaps old
             owner -> ADMIN and new owner -> OWNER atomically, so the "exactly one owner" invariant
             holds by construction (found seeds it, transfer moves it, nothing ever deletes it).

This is the pure ENGINE the org/club feature-block is built on — DB-free and dependency-free, the
same shape as tournaments.py / leagues.py / practice.py / competitions.py / nearby.py / messenger.py
/ highlights.py / feed.py. Persistence is deferred on purpose: the accounts table (id, name, handle
unique, kind, created_at) and the memberships table (org, player, role — unique per (org, player))
land with the batched migrations (item #19, SPEC Y5 — no session applies schema); the club profile,
the roster and the manage controls land on the UI. So the Clubs screen lands as dummy UI now (SPEC
Y1, blocks.py: orgs off -> dummy) with this engine proven and preflight-gated behind it.

Privacy/permission at the public boundary (who may SEE a club, block/report, the 16+ gate) are the
public layer's job (item #16). This engine enforces only what an account cannot exist without: a
profile has a real name/handle/kind, and the role graph always keeps exactly one owner while letting
managers run the roster. Handle UNIQUENESS is a DB constraint (item #19), not an app scan — a pure
engine holds no registry of every handle, so it validates the shape and leaves the collision to the
unique index, the same way feed leaves id assignment to the DB.

Model — plain dicts, no DB (ids are anything hashable+comparable — the app's player/org ids are ints):
  account     — {"name", "handle", "kind"}; caller stamps id + created_at.
  membership  — {"org", "player", "role"}; role one of OWNER | ADMIN | MEMBER. Unique per (org, player).

check() proves the profile trust guards, the role reads, the whole manage lifecycle (add / set_role /
remove / transfer with every permission + the protected-owner invariant), and purity — same fail-loud
shape as the sibling engines, wired into deploy.py preflight.
"""
import re

# --- account kinds ---------------------------------------------------------------------------
CLUB = "club"
ORG = "org"
KINDS = (CLUB, ORG)

# --- roles (a ladder — higher rank manages lower) --------------------------------------------
OWNER = "owner"
ADMIN = "admin"
MEMBER = "member"
ROLES = (OWNER, ADMIN, MEMBER)
RANK = {OWNER: 3, ADMIN: 2, MEMBER: 1}          # strictly higher rank may manage a lower one

# public @handle: 3-30 of lowercase a-z, 0-9, underscore (a club is addressed by it)
_HANDLE = re.compile(r"[a-z0-9_]{3,30}")


# --- account profile (the trust boundary) ----------------------------------------------------
def normalize_handle(handle):
    """Normalize a public @handle: strip, drop a leading '@', lowercase. Fails loud unless the result
    is 3-30 chars of a-z / 0-9 / underscore — it names the account publicly, so it can't be blank or
    hold spaces/punctuation. Uniqueness is the DB's job (item #19), not this engine's."""
    h = (handle or "").strip().lstrip("@").lower()
    if not _HANDLE.fullmatch(h):
        raise ValueError(f"handle must be 3-30 chars of a-z, 0-9, _ (got {handle!r})")
    return h


def account(name, handle, kind=CLUB):
    """Build a validated account profile (the caller stamps its id + created_at and persists it).
    Trust-boundary guards, since name/handle arrive from a user: the display name is non-empty
    (whitespace-only rejected) and stored stripped, the handle is normalized + charset-checked, and
    the kind is a club or an org. Returns {"name", "handle", "kind"} only."""
    nm = (name or "").strip()
    if not nm:
        raise ValueError("account name is empty")
    if kind not in KINDS:
        raise ValueError(f"unknown account kind {kind!r} (want {KINDS})")
    return {"name": nm, "handle": normalize_handle(handle), "kind": kind}


# --- role reads ------------------------------------------------------------------------------
def _membership(org, player, members):
    """The (org, player) membership row, or None — one row per pair, so the first match is the only."""
    for m in members:
        if m["org"] == org and m["player"] == player:
            return m
    return None


def role_of(org, player, members):
    """`player`'s role in `org` (OWNER | ADMIN | MEMBER), or None if they don't belong."""
    m = _membership(org, player, members)
    return m["role"] if m else None


def is_member(org, player, members):
    """True if `player` belongs to `org` in any role."""
    return _membership(org, player, members) is not None


def can_manage(org, player, members):
    """True if `player` may run the member roster — the owner or an admin (rank >= ADMIN). The bit the
    manage controls read to decide whether to show add/remove at all."""
    return RANK.get(role_of(org, player, members), 0) >= RANK[ADMIN]


def roster(org, members):
    """`org`'s members for its Club page — owner first, then admins, then members; stable within a
    rank (insertion order preserved, since sort is stable). The membership dicts are returned as-is."""
    return sorted((m for m in members if m["org"] == org), key=lambda m: -RANK[m["role"]])


def orgs_of(player, members):
    """The accounts `player` belongs to, as {org: role} — the "Clubs" list on their profile."""
    return {m["org"]: m["role"] for m in members if m["player"] == player}


# --- the role lifecycle (each returns records/list for the caller to persist; inputs untouched) --
def found(org, owner):
    """The account's founding membership: `owner` seated as its sole OWNER. Every account starts here
    with exactly one owner; it moves only via transfer() and is never removed, so the invariant holds
    by construction. Returns {"org", "player": owner, "role": OWNER}."""
    return {"org": org, "player": owner, "role": OWNER}


def add(org, actor, player, members):
    """`actor` (an admin or the owner) admits `player` to `org` as a MEMBER. Returns the new membership
    (the caller persists it); `members` is untouched. New members always join at MEMBER — granting
    ADMIN is a separate, owner-only act (set_role). Fails loud if `actor` may not manage the account,
    or `player` already belongs (one row per (org, player))."""
    if not can_manage(org, actor, members):
        raise ValueError(f"{actor!r} may not manage account {org!r}")
    if is_member(org, player, members):
        raise ValueError(f"{player!r} is already a member of {org!r}")
    return {"org": org, "player": player, "role": MEMBER}


def set_role(org, actor, player, role, members):
    """The owner promotes/demotes a member between MEMBER and ADMIN. Returns the updated membership;
    `members` untouched. Owner-only — granting management authority is the owner's call. It cannot set
    OWNER (ownership moves only via transfer(), which keeps exactly one owner) nor touch the owner's
    own row. Fails loud on a non-owner actor, an unknown role, OWNER as the target role, or a target
    who isn't a (non-owner) member."""
    if role_of(org, actor, members) != OWNER:
        raise ValueError(f"only the owner may set roles in {org!r}")
    if role not in (ADMIN, MEMBER):
        raise ValueError(f"set_role sets ADMIN or MEMBER, not {role!r} (ownership moves via transfer)")
    target = _membership(org, player, members)
    if target is None:
        raise ValueError(f"{player!r} is not a member of {org!r}")
    if target["role"] == OWNER:
        raise ValueError("cannot change the owner's role — transfer() ownership instead")
    return {"org": org, "player": player, "role": role}


def remove(org, actor, player, members):
    """Drop `player` from `org`. Two ways in: a self-leave (`player` == `actor`), or `actor` removing
    someone of STRICTLY lower role (owner removes admins/members, admin removes members). The OWNER is
    never removable — not by anyone, and not by leaving — so the account always keeps its one owner;
    transfer() ownership first. Returns a NEW members list without that row; the input is untouched.
    Fails loud if `player` isn't a member, is the owner, or `actor` lacks the rank."""
    target = _membership(org, player, members)
    if target is None:
        raise ValueError(f"{player!r} is not a member of {org!r}")
    if target["role"] == OWNER:
        raise ValueError("the owner cannot be removed — transfer() ownership first")
    if actor != player:                              # not a self-leave -> actor must outrank the target
        if RANK.get(role_of(org, actor, members), 0) <= RANK[target["role"]]:
            raise ValueError(f"{actor!r} may not remove {player!r} from {org!r} (needs a higher role)")
    return [m for m in members if not (m["org"] == org and m["player"] == player)]


def transfer(org, owner, to, members):
    """Hand ownership from `owner` to `to` (an existing member). The ONLY way OWNER moves: returns the
    TWO updated memberships — [old owner -> ADMIN, new owner -> OWNER] — for the caller to persist
    together, so the account is never ownerless and never two-owned. `members` untouched. Fails loud
    if `actor` isn't the owner, `to` isn't a member, or `to` is already the owner."""
    if role_of(org, owner, members) != OWNER:
        raise ValueError(f"only the owner may transfer ownership of {org!r}")
    if to == owner:
        raise ValueError("already the owner")
    if not is_member(org, to, members):
        raise ValueError(f"{to!r} is not a member of {org!r} — add them first")
    return [{"org": org, "player": owner, "role": ADMIN},
            {"org": org, "player": to, "role": OWNER}]


def owners(org, members):
    """The owner ids of `org` — always exactly one for a well-formed account. Used by check()'s
    invariant assertions and available to a persistence-layer guard."""
    return [m["player"] for m in members if m["org"] == org and m["role"] == OWNER]


def check():
    """Fail loud (ValueError) if the org/club engine regressed. Returns True when clean."""
    bad = []

    # 1. PROFILE TRUST GUARDS — name non-empty (stripped), handle normalized (@ dropped, lowercased,
    #    charset+length enforced), kind a club or org. name/handle arrive from a user.
    a = account("  Baseline Tennis Club  ", "@Baseline_TC", ORG)
    if a != {"name": "Baseline Tennis Club", "handle": "baseline_tc", "kind": ORG}:
        bad.append(f"account built the wrong profile: {a}")
    if account("X", "smash").get("kind") != CLUB:               # kind defaults to club
        bad.append("account kind did not default to club")
    for op in (lambda: account("   ", "smash"),                 # whitespace-only name
               lambda: account("", "smash"),                    # empty name
               lambda: account("Ok", "ab"),                     # handle too short (<3)
               lambda: account("Ok", "a b"),                    # handle has a space
               lambda: account("Ok", "smash!"),                 # handle bad charset
               lambda: account("Ok", "x" * 31),                 # handle too long (>30)
               lambda: account("Ok", "smash", "league")):       # unknown kind
        try:
            op()
            bad.append("account accepted an invalid profile")
        except ValueError:
            pass

    # 2. FOUND + ROLE READS — the creator is the sole OWNER; role_of / is_member / can_manage read it.
    f = found("c1", 1)
    if f != {"org": "c1", "player": 1, "role": OWNER}:
        bad.append(f"found seated the wrong owner: {f}")
    m0 = [f]
    if role_of("c1", 1, m0) != OWNER or role_of("c1", 9, m0) is not None:
        bad.append("role_of wrong for owner / stranger")
    if not is_member("c1", 1, m0) or is_member("c1", 9, m0):
        bad.append("is_member wrong")
    if not can_manage("c1", 1, m0):                             # owner manages
        bad.append("owner should be able to manage")
    if owners("c1", m0) != [1]:
        bad.append("a founded account must have exactly one owner")

    # 3. ADD — a manager admits a MEMBER; a non-manager / a duplicate are refused.
    add2 = add("c1", 1, 2, m0)                                  # owner adds player 2
    if add2 != {"org": "c1", "player": 2, "role": MEMBER}:
        bad.append(f"add built the wrong membership: {add2}")
    m1 = m0 + [add2]
    if can_manage("c1", 2, m1):                                 # a plain member does NOT manage
        bad.append("a plain member should not manage")
    for op in (lambda: add("c1", 2, 3, m1),                     # a MEMBER cannot add
               lambda: add("c1", 7, 3, m1),                     # a stranger cannot add
               lambda: add("c1", 1, 2, m1)):                    # 2 already a member
        try:
            op()
            bad.append("add allowed an illegal add")
        except ValueError:
            pass

    # 4. SET_ROLE — the owner promotes MEMBER 2 -> ADMIN (who can then manage but still not set roles),
    #    and demotes back; a non-owner / OWNER-as-role / a non-member / targeting the owner are refused.
    up = set_role("c1", 1, 2, ADMIN, m1)
    if up != {"org": "c1", "player": 2, "role": ADMIN}:
        bad.append(f"set_role did not promote to admin: {up}")
    m2 = [up if (x["org"], x["player"]) == ("c1", 2) else x for x in m1]
    if not can_manage("c1", 2, m2):                            # a promoted admin now manages the roster
        bad.append("a promoted admin should be able to manage")
    if set_role("c1", 1, 2, MEMBER, m2)["role"] != MEMBER:    # ...and can be demoted back
        bad.append("set_role did not demote back to member")
    for op in (lambda: set_role("c1", 2, 1, MEMBER, m2),      # an admin cannot set roles (owner-only)
               lambda: set_role("c1", 1, 2, OWNER, m2),       # cannot grant OWNER via set_role
               lambda: set_role("c1", 1, 9, ADMIN, m2),       # 9 is not a member
               lambda: set_role("c1", 1, 1, MEMBER, m2)):     # cannot demote the owner
        try:
            op()
            bad.append("set_role allowed an illegal change")
        except ValueError:
            pass

    # 5. REMOVE — a self-leave; an admin removes a member; strict-rank + protected-owner guards; and
    #    the returned list drops exactly that row while the input is untouched.
    left = remove("c1", 2, 2, m1)                              # member 2 leaves themselves
    if any(x["player"] == 2 for x in left) or len(m1) != 2:   # dropped from the copy; input intact
        bad.append("self-leave did not drop exactly the leaver (or mutated the input)")
    kicked = remove("c1", 1, 2, m1)                            # owner removes member 2
    if [x["player"] for x in kicked] != [1]:
        bad.append(f"owner-remove wrong: {[x['player'] for x in kicked]}")
    # admin(2) vs member(3): admin may remove the member; member may not remove the admin or a peer.
    trio = [found("c1", 1), {"org": "c1", "player": 2, "role": ADMIN},
            {"org": "c1", "player": 3, "role": MEMBER}, {"org": "c1", "player": 4, "role": MEMBER}]
    if [x["player"] for x in remove("c1", 2, 3, trio)] != [1, 2, 4]:   # admin removes member 3
        bad.append("an admin should be able to remove a member")
    for op in (lambda: remove("c1", 3, 2, trio),              # member cannot remove an admin
               lambda: remove("c1", 3, 4, trio),              # member cannot remove a peer member
               lambda: remove("c1", 2, 1, trio),              # admin cannot remove the owner
               lambda: remove("c1", 1, 1, trio),              # the owner cannot leave
               lambda: remove("c1", 1, 9, trio)):             # 9 is not a member
        try:
            op()
            bad.append("remove allowed an illegal removal")
        except ValueError:
            pass

    # 6. TRANSFER — the ONLY way OWNER moves: old owner -> ADMIN, new owner -> OWNER, still exactly one
    #    owner. A non-owner actor / a non-member target / transferring to yourself are refused.
    pair = [found("c1", 1), {"org": "c1", "player": 2, "role": ADMIN}]
    handed = transfer("c1", 1, 2, pair)
    got = {(x["player"], x["role"]) for x in handed}
    if got != {(1, ADMIN), (2, OWNER)}:
        bad.append(f"transfer did not swap owner<->admin: {got}")
    after = [handed[0] if x["player"] == 1 else handed[1] if x["player"] == 2 else x for x in pair]
    if owners("c1", after) != [2]:                            # exactly one owner, and it's the new one
        bad.append("after transfer the account must have exactly one (new) owner")
    for op in (lambda: transfer("c1", 2, 1, pair),            # 2 is not the owner
               lambda: transfer("c1", 1, 9, pair),            # 9 is not a member
               lambda: transfer("c1", 1, 1, pair)):           # already the owner
        try:
            op()
            bad.append("transfer allowed an illegal transfer")
        except ValueError:
            pass

    # 7. READS — roster is owner-first then admins then members; orgs_of lists a player's clubs+roles.
    club = [{"org": "c1", "player": 3, "role": MEMBER}, found("c1", 1),
            {"org": "c1", "player": 2, "role": ADMIN}, {"org": "c2", "player": 1, "role": MEMBER}]
    if [x["player"] for x in roster("c1", club)] != [1, 2, 3]:   # owner, admin, member
        bad.append(f"roster order wrong: {[x['player'] for x in roster('c1', club)]}")
    if orgs_of(1, club) != {"c1": OWNER, "c2": MEMBER}:
        bad.append(f"orgs_of wrong: {orgs_of(1, club)}")

    if bad:
        raise ValueError("org/club engine regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print(f"orgs OK: account profiles (kinds {KINDS}) + a protected-owner role graph {ROLES} "
          f"(found / add / set_role / remove / transfer, exactly one owner always)")
