"""Shared test helpers for the clean-foundation (global uuid) model."""
import importlib
import sqlite3
import pytest

import db as dbmod
import auth as authmod


def mem():
    """In-memory SQLite mirroring the live clean schema."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(dbmod.SCHEMA)
    return con


def mkplayer(con, name, real=None, pid=None):
    """Create a global player (id = a uuid, mimicking auth.users.id). Returns the id."""
    pid = pid or dbmod.gen_uuid()
    dbmod.create_player(con, pid, name, real)
    return pid


def bearer(sub, email=None):
    return "Bearer " + authmod.mint_mock_token(sub, email or (sub + "@t.com"))


def _fresh_app(tmp_path):
    dbmod.DATABASE_URL = ""
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    return appmod


@pytest.fixture
def app_client(tmp_path):
    from fastapi.testclient import TestClient
    appmod = _fresh_app(tmp_path)
    c = TestClient(appmod.app)
    c.app_mod = appmod
    return c


def signin(c, sub, name=None, real=None):
    """Sign in as `sub`; if name given, create the player. Returns (player_id, headers)."""
    h = {"Authorization": bearer(sub)}
    if name is not None:
        c.post("/api/me/claim", json={"name": name, "real_name": real}, headers=h)
    return sub, h
