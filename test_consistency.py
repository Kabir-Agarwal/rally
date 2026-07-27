"""Task 2d: client engine === server replay === Python scorer, for the same points.

Simulates a multi-set per-point match through the JS client engine (via node), replays the
identical points to the live-scoring endpoint, and asserts the stored server sets match the
client's — and the pure Python scorer agrees too. Skips cleanly if node is unavailable."""
import json
import shutil
import subprocess
import importlib
from pathlib import Path

import pytest

import db as dbmod
import scoring

NODE = shutil.which("node")
CLI = Path(__file__).parent / "engine_cli.cjs"


def _client(tmp_path):
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    from fastapi.testclient import TestClient
    c = TestClient(appmod.app)
    c.headers.update({"Authorization": "Bearer " + appmod.auth.mint_mock_token("u1", "u1@test"),
                      "X-Admin-Key": appmod.ADMIN_KEY})
    return c


def _build_points():
    """Two full sets for side 1 (6-0, 6-0) then a partial third set (2 games) — 3-set shape."""
    seq = []
    for _ in range(2):                      # two 6-0 sets
        for _g in range(6):
            seq += [1, 1, 1, 1]
    for _g in range(2):                     # partial 3rd set, 2 games to side 1
        seq += [1, 1, 1, 1]
    # sprinkle a contested game (deuce battle) won by side 2
    seq += [1, 1, 2, 2, 1, 2, 2, 2]
    return seq


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_client_engine_matches_server_replay(tmp_path):
    points = _build_points()

    # 1) client engine (JS) via node
    out = subprocess.run([NODE, str(CLI), json.dumps(points)], capture_output=True, text=True, check=True)
    client_sets = [list(x) for x in json.loads(out.stdout)]

    # 2) pure Python scorer
    py_sets = [list(x) for x in scoring.all_sets_for_storage(points)]
    assert client_sets == py_sets, "client engine disagrees with Python scorer"

    # 3) server replay: post each point, then read stored sets (global model, no group)
    from conftest import signin
    c = _client(tmp_path)
    a, ha = signin(c, "a", "A")
    b, hb = signin(c, "b", "B")
    mid = c.post("/api/match/start",
                 json={"kind": "singles", "side1": [a], "side2": [b], "group": None}, headers=ha).json()["id"]
    last = None
    for w in points:
        last = c.post(f"/api/match/{mid}/point", json={"winner_side": w}, headers=ha).json()
    server_sets = [[s["g1"], s["g2"]] for s in last["sets"]]

    assert server_sets == client_sets, "server replay state != client engine state"
