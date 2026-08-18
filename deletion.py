"""Delete-past-matches contract — deletion is a SOFT, reversible tombstone, frozen so a later block
can't silently turn it into a hard purge or stop rolling back a deleted match's rating (SPEC Y2).

Y2 KEEP: delete-past-matches. Rally is LIVE and Y3 features land block by block (item #2); several of
the planned ones — tournaments, leagues, the practice-vs-rated split — touch the match lifecycle and
the rating pipeline. "Delete a past match" (logic.delete_match, via /api/match/{id}/delete and the
admin route) is a *soft* delete: db.set_status stamps status='deleted' and PRESERVES the row, the
rating rebuild reads only status='counted' so a deleted match's contribution vanishes on the next
read (db._rating_match_dicts), and the match drops out of counts (`status<>'deleted'`) and the
visible-history allow-list.

check() exercises the real logic+db+ratings engine end-to-end on an in-memory DB and fails loud if
any of that regressed — same shape as blocks.validate() / theme.check() / chemistry.check(), wired
into the same deploy.py preflight, so "keep delete-past-matches" is enforced, not hoped for.
"""
import db
import logic
from ratings import START


def _counted_singles():
    """Fresh in-memory app DB with one COUNTED singles match (A beat B 6-4). Returns (con, a, b, mid)."""
    con = db.connect(":memory:")
    con.executescript(db.SCHEMA)
    a, b = db.gen_uuid(), db.gen_uuid()
    db.create_player(con, a, "A")
    db.create_player(con, b, "B")
    mid = logic.start_match(con, None, "singles", [a], [b], [], a)  # logger a
    logic.edit_sets(con, mid, [(6, 4)])
    logic.finish_match(con, mid)   # logger a auto-approves -> pending_approval
    logic.approve(con, mid, b)     # both approved -> counted
    return con, a, b, mid


def check():
    """Fail loud (ValueError) if the delete-past-matches contract regressed. Returns True when clean."""
    bad = []

    con, a, b, mid = _counted_singles()
    if db.match_row(con, mid)["status"] != "counted" or db.rating_state(con)["singles"].get(a, START) <= START:
        bad.append("setup: a counted singles match did not lift the winner above baseline")

    res = logic.delete_match(con, mid)
    if res != "deleted":
        bad.append(f"delete_match returned {res!r}, want 'deleted'")

    # 1. SOFT: the row is preserved and stamped 'deleted' — never physically removed (audit + rollback).
    row = db.match_row(con, mid)
    if row is None:
        bad.append("delete_match physically removed the match row (delete must be SOFT — tombstone, not purge)")
    elif row["status"] != "deleted":
        bad.append(f"delete_match left status {row['status']!r}, want 'deleted'")

    # 2. AUDIT: child rows survive the tombstone — a hard delete / cascade would wipe them.
    if row is not None and not db.match_sets(con, mid):
        bad.append("delete_match dropped the match's sets (a soft delete must keep the row's children)")

    # 3. ROLLBACK: a deleted past (counted) match no longer counts toward ratings — winner to baseline.
    after = db.rating_state(con)["singles"].get(a, START)
    if after != START:
        bad.append(f"winner rating is {after} after deleting the only counted match "
                   f"(want baseline {START} — deleting a past match did not roll back its rating)")

    # 4. HIDDEN: a deleted match drops out of counts (admin overview counts `status<>'deleted'`).
    live_count = con.execute("SELECT COUNT(*) c FROM matches WHERE status<>'deleted'").fetchone()["c"]
    if live_count != 0:
        bad.append(f"non-deleted match count is {live_count} after deleting the only match "
                   f"(want 0 — deleted matches must be excluded from counts)")

    # 5. GUARD: deleting a match that isn't there is a clean ValueError (the route relies on it -> 400).
    try:
        logic.delete_match(con, db.gen_uuid())
        bad.append("delete_match on a missing id did not raise (route relies on the ValueError -> 400)")
    except ValueError:
        pass

    # 6. SCHEMA: 'deleted' stays a legal terminal status — drop it from the enum and soft delete blows up.
    if "'deleted'" not in db.SCHEMA:
        bad.append("'deleted' is no longer a permitted match status in db.SCHEMA (soft delete needs it)")

    if bad:
        raise ValueError("delete-past-matches regressed:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    print("deletion OK: soft reversible tombstone, rating rolls back, hidden from counts")
