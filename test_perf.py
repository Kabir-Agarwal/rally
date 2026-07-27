"""Local endpoint latency budget (<300ms each) on the global model."""
import time
from conftest import signin


def _timed(fn):
    fn()
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def test_core_endpoints_under_300ms(app_client):
    c = app_client
    a, ha = signin(c, "a", "A")
    b, hb = signin(c, "b", "B")
    for _ in range(6):
        mid = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                     headers=ha).json()["id"]
        c.post(f"/api/match/{mid}/sets", json={"sets": [[6, 4]]}, headers=ha)
        c.post(f"/api/match/{mid}/finish", json={}, headers=ha)
        c.post(f"/api/match/{mid}/approve", json={}, headers=hb)     # counted
    live = c.post("/api/match/start", json={"kind": "singles", "side1": [a], "side2": [b], "group": None},
                  headers=ha).json()["id"]
    budgets = {
        "leaderboard": lambda: c.get("/api/leaderboard?mode=singles", headers=ha),
        "live": lambda: c.get("/api/live", headers=ha),
        "history": lambda: c.get("/api/history", headers=ha),
        "point": lambda: c.post(f"/api/match/{live}/point", json={"winner_side": 1}, headers=ha),
    }
    slow = {name: round(_timed(fn), 1) for name, fn in budgets.items()}
    for name, ms in slow.items():
        assert ms < 300, f"{name} took {ms}ms (>300ms budget)"
