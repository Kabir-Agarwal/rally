"""Guard the batched-migrations convention (SPEC Y5) + the "no session applies schema" invariant.

Y5: one migrations/block-N.sql per feature-block -> ONE planned owner pause -> the owner's chat-Claude
applies each via the Supabase MCP -> continue. No build session ever applies schema.

This is a STRUCTURAL check, NOT an apply — it never runs a migration (that would itself violate Y5).
It proves every block-N.sql is named right, carries the PROPOSED / NOT-APPLIED + no-session-applies
header (so no file can masquerade as auto-runnable), holds real DDL, and that db.init_db still only
VERIFIES the schema on Postgres (require_schema) and never creates or patches it.

Wired into deploy.py preflight beside the engine check()s; also runnable alone:
    python migrations/check_migrations.py
"""
import re
import sys
import inspect
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))   # repo root, so `import db` resolves when run as a script
BLOCK_RE = re.compile(r"^block-(\d+)\.sql$")
# Two markers every batched migration must carry, so a file can't look auto-runnable (SPEC Y5).
REQUIRED_MARKERS = ("PROPOSED / NOT APPLIED", "No session applies schema")


def block_files():
    return sorted(HERE.glob("block-*.sql"))


def check():
    """Fail loud (ValueError) if the batched-migrations convention regressed. Returns True when clean."""
    bad = []

    files = block_files()
    if not files:
        bad.append("no migrations/block-N.sql files — the batched convention has nothing to apply")
    seen = {}
    for p in files:
        m = BLOCK_RE.match(p.name)
        if not m:
            bad.append(f"{p.name}: not the block-N.sql naming convention")
            continue
        n = int(m.group(1))
        if n in seen:
            bad.append(f"block number {n} used twice: {seen[n]} and {p.name}")
        seen[n] = p.name
        text = p.read_text(encoding="utf-8")
        low = text.lower()
        for marker in REQUIRED_MARKERS:
            if marker.lower() not in low:
                bad.append(f"{p.name}: missing mandatory header marker {marker!r}")
        if not re.search(r"\b(create|alter)\b", text, re.I):
            bad.append(f"{p.name}: no CREATE/ALTER DDL — an empty migration")
        if ";" not in text:
            bad.append(f"{p.name}: no statement terminator ';'")

    # The Y5 invariant, in code: the app VERIFIES schema on Postgres, never creates/patches it.
    # ponytail: string-inspect db.init_db's PG branch (before its early return); update if that
    # function is refactored — the invariant it guards is the point, not this exact parse.
    import db
    src = inspect.getsource(db.init_db)
    pg_branch = src[:src.index("return")]        # the _is_pg() path, up to its early return
    if "require_schema" not in pg_branch:
        bad.append("db.init_db PG path must call require_schema (verify, never create)")
    if "executescript" in pg_branch or "apply_migration" in pg_branch:
        bad.append("db.init_db PG path applies schema — SPEC Y5 forbids a session ever applying it")

    if bad:
        raise ValueError("batched-migrations convention broken:\n  " + "\n  ".join(bad))
    return True


if __name__ == "__main__":
    check()
    n = len(block_files())
    print(f"migrations OK: {n} batched block file(s), all PROPOSED / NOT APPLIED; "
          f"db verifies (never applies) schema on Postgres.")
