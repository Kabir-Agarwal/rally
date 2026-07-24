"""Task 2e: local endpoint latency budget (<300ms each). Uses a warm in-process client."""
import time
import importlib
import db as dbmod


def _client(tmp_path):
    dbmod.DB_PATH = tmp_path / "t.db"
    import app as appmod
    importlib.reload(appmod)
    appmod.db.DB_PATH = tmp_path / "t.db"
    appmod.db.init_db(tmp_path / "t.db")
    orig = appmod.db.connect
    appmod.db.connect = lambda path=tmp_path / "t.db": orig(path)
    from fastapi.testclient import TestClient
    return TestClient(appmod.app)


def _timed(fn):
    fn()  # warm once (import/JIT/template compile) then measure
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def test_core_endpoints_under_300ms(tmp_path):
    c = _client(tmp_path)
    code = c.post("/api/group/create", json={"name": "PERF"}).json()["code"]
    a = c.post(f"/g/{code}/api/player", json={"name": "A"}).json()["id"]
    b = c.post(f"/g/{code}/api/player", json={"name": "B"}).json()["id"]
    # seed a few finished matches so recompute has real work
    for _ in range(6):
        mid = c.post(f"/g/{code}/api/match/start",
                     json={"kind": "singles", "side1": [a], "side2": [b], "logger": a}).json()["id"]
        c.post(f"/g/{code}/api/match/{mid}/sets", json={"sets": [[6, 4]]})
        c.post(f"/g/{code}/api/match/{mid}/finish", json={})
    live = c.post(f"/g/{code}/api/match/start",
                  json={"kind": "singles", "side1": [a], "side2": [b], "logger": a}).json()["id"]

    budgets = {
        "leaderboard": lambda: c.get(f"/g/{code}/api/leaderboard?scope=group&mode=singles"),
        "live": lambda: c.get(f"/g/{code}/api/live"),
        "history": lambda: c.get(f"/g/{code}/api/history"),
        "point": lambda: c.post(f"/g/{code}/api/match/{live}/point", json={"winner_side": 1}),
    }
    slow = {name: round(_timed(fn), 1) for name, fn in budgets.items()}
    for name, ms in slow.items():
        assert ms < 300, f"{name} took {ms}ms (>300ms budget)"
