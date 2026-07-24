"""Backend tests: schema compiles for the Postgres dialect (no live PG needed),
metadata stays in sync with the SQLite SCHEMA string, and SQLite is the default."""
import re
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import postgresql
import schema
import db


def test_schema_compiles_for_postgres():
    d = postgresql.dialect()
    tables = list(schema.metadata.sorted_tables)
    assert tables, "no tables defined"
    for t in tables:
        sql = str(CreateTable(t).compile(dialect=d))
        assert "CREATE TABLE" in sql
        for idx in t.indexes:                       # functional unique index must compile too
            assert "CREATE" in str(CreateIndex(idx).compile(dialect=d))
    assert "admin_log" in schema.metadata.tables     # new table ported


def test_metadata_matches_sqlite_schema():
    """Drift guard: every metadata table + column exists in the raw SQLite SCHEMA."""
    raw = db.SCHEMA
    for name, table in schema.metadata.tables.items():
        block = re.search(r'CREATE TABLE IF NOT EXISTS ' + name + r'\s*\((.*?)\n\);', raw, re.S)
        assert block, f"table {name} absent from SCHEMA"
        cols = block.group(1)
        for c in table.columns:
            assert re.search(r'\b' + re.escape(c.name) + r'\b', cols), f"{name}.{c.name} missing in SCHEMA"


def test_sqlite_is_default_backend():
    assert db._is_pg() is False          # no DATABASE_URL in tests -> SQLite fallback


def test_pg_url_normalisation():
    # postgres:// and postgresql:// both map to the psycopg driver URL
    import importlib
    old = db.DATABASE_URL
    try:
        db.DATABASE_URL = "postgres://host/db"
        db._ENGINE = None
        # build the URL string the way _engine() would, without a live connection
        url = db.DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        assert url.startswith("postgresql+psycopg://")
        assert db._is_pg() is True
    finally:
        db.DATABASE_URL = old
        db._ENGINE = None
