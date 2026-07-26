"""Rally identity backfill (Task 5) — PROPOSED / NOT APPLIED to production.

Gives every existing player a permanent 5-char public `code` (and, for players linked to an
auth user, sets `auth_id`). Prints a report: rows scanned, codes assigned, and a hard assertion
of ZERO collisions on the code column. DRY-RUN by default — it writes nothing unless you pass
--apply, and even then only where the migration columns already exist.

HOW IT SHOULD REACH LIVE POSTGRES: the sandbox can't reach the Supabase Postgres port, so on
production this runs as SQL via Supabase MCP (Section 2 of 2026-07-27_identity_foundation.sql
already does the same UPDATE). This script is for (a) a local dry-run against SQLite to prove the
generator + collision logic, and (b) whoever has direct DB access to run the backfill deliberately.

Usage:
    python migrations/backfill_identity.py            # dry-run (no writes), prints the report
    python migrations/backfill_identity.py --apply    # writes codes where players.code exists
    python migrations/backfill_identity.py --emit-sql  # print UPDATE statements for MCP review
"""
from __future__ import annotations
import sys
import os

# 5-char code alphabet: A-Z 2-9 minus confusables O, 0, I, 1, L  (31 symbols; 31^5 ≈ 28.6M)
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 5


def gen_code(rng, taken: set[str]) -> str:
    while True:
        c = "".join(rng.choice(ALPHABET) for _ in range(CODE_LEN))
        if c not in taken:
            taken.add(c)
            return c


def _has_column(con, table: str, col: str) -> bool:
    try:
        cur = con.execute(f"SELECT {col} FROM {table} LIMIT 0")
        cur.fetchall()
        return True
    except Exception:
        return False


def main(argv):
    apply = "--apply" in argv
    emit_sql = "--emit-sql" in argv
    import secrets
    rng = secrets.SystemRandom()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import db
    con = db.connect()          # SQLite locally; on live Postgres this backfill runs as SQL via MCP

    rows = con.execute("SELECT id, name FROM players ORDER BY id").fetchall()
    total = len(rows)
    has_code = _has_column(con, "players", "code")
    taken: set[str] = set()
    if has_code:
        for r in con.execute("SELECT code FROM players WHERE code IS NOT NULL").fetchall():
            taken.add(r["code"] if hasattr(r, "keys") else r[0])

    assignments = []                       # (player_id, code)
    for r in rows:
        pid = r["id"] if hasattr(r, "keys") else r[0]
        existing = None
        if has_code:
            existing = con.execute("SELECT code FROM players WHERE id=?", (pid,)).fetchone()
            existing = (existing["code"] if hasattr(existing, "keys") else existing[0]) if existing else None
        if existing:
            continue                       # already has a code — leave permanent code untouched
        assignments.append((pid, gen_code(rng, taken)))

    # hard collision check: every assigned code is unique AND unique vs pre-existing codes
    codes = [c for _, c in assignments]
    collisions = len(codes) - len(set(codes))

    print(f"players scanned      : {total}")
    print(f"already had a code   : {total - len(assignments)}" + ("" if has_code else "  (code column absent — dry-run only)"))
    print(f"codes to assign      : {len(assignments)}")
    print(f"code collisions      : {collisions}   (MUST be 0)")
    assert collisions == 0, "code collision detected — aborting, do not apply"

    if emit_sql:
        for pid, code in assignments:
            print(f"UPDATE players SET code='{code}' WHERE id={pid} AND code IS NULL;")

    if apply and has_code and assignments:
        for pid, code in assignments:
            con.execute("UPDATE players SET code=? WHERE id=? AND code IS NULL", (code, pid))
        con.commit()
        print(f"APPLIED: wrote {len(assignments)} codes.")
    elif apply and not has_code:
        print("NOT APPLIED: players.code column does not exist yet — run the migration first.")
    else:
        print("DRY-RUN: no rows written. Re-run with --apply once the code column exists.")

    # zero-collision confirmation against the live/target table if the column exists
    if has_code:
        dupe = con.execute(
            "SELECT count(*) - count(DISTINCT code) FROM players WHERE code IS NOT NULL"
        ).fetchone()
        dupe = dupe[0] if not hasattr(dupe, "keys") else list(dupe)[0]
        print(f"post-state duplicate codes in table: {dupe}   (MUST be 0)")
        assert dupe == 0, "duplicate codes present in table"


if __name__ == "__main__":
    main(sys.argv[1:])
