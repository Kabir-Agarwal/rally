"""Rally — tennis scorer. FastAPI app. Phone-first, no accounts, groups reached by 6-char code.

The group code in the URL is the capability: possessing it = member = can write.
# ponytail: no server-side session/accounts. Code = auth. Public/private governs the
# global (cross-group) feeds only; the read-only "watch" UX is client state. Add real
# auth only if groups ever need to exclude code-holders — out of scope (v2).

Admin god-mode lives behind one secret ADMIN_KEY (from .env / env var). See CONTEXT.md.
"""
from __future__ import annotations
import os
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import logic
import scoring
import ratings
from ratings import START

BASE = Path(__file__).parent
app = FastAPI(title="Rally")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

db.init_db()


def _load_admin_key():
    # ponytail: manual .env read, no python-dotenv dependency for one value.
    v = os.environ.get("ADMIN_KEY")
    if v:
        return v.strip()
    env = BASE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ADMIN_KEY="):
                return line.split("=", 1)[1].strip()
    return "dev-admin-key-change-me"


ADMIN_KEY = _load_admin_key()


# --- helpers --------------------------------------------------------------
def get_con():
    con = db.connect()
    # v2: no approval/deadline machinery — results count immediately on finish.
    return con


def require_group(con, code):
    g = db.group_by_code(con, code)
    if not g:
        raise HTTPException(404, "group not found")
    return g


def live_player_ids(con, group_id):
    rows = con.execute(
        "SELECT DISTINCT mp.player_id FROM match_players mp JOIN matches m ON m.id=mp.match_id "
        "WHERE m.group_id=? AND m.status='live' AND m.deleted=0", (group_id,)
    ).fetchall()
    return {r["player_id"] for r in rows}


def match_view(con, m):
    """Serialize a match for JSON / templates (scoresheet, names, live point state)."""
    mid = m["id"]
    mps = db.match_players(con, mid)
    s1 = [{"id": r["player_id"], "name": r["name"]} for r in mps if r["side"] == 1]
    s2 = [{"id": r["player_id"], "name": r["name"]} for r in mps if r["side"] == 2]
    rot = [{"id": r["player_id"], "name": r["name"], "pos": r["rotation_pos"]}
           for r in mps if r["rotation_pos"]]
    rot.sort(key=lambda x: x["pos"])
    v = {"id": mid, "kind": m["kind"], "status": m["status"], "played_on": m["played_on"],
         "side1": s1, "side2": s2, "rotation": rot}

    if m["kind"] == "tt":
        games = db.tt_games(con, mid)
        tally = {}
        for r in rot:
            tally[r["id"]] = 0
        for gm in games:
            if gm["winner_player_id"] in tally:
                tally[gm["winner_player_id"]] += 1
        rotation_ids = [r["id"] for r in rot]
        gi = len(games)
        pairing = None
        if len(rotation_ids) == 3:
            srv, rec, sit = scoring.tt_pairing(rotation_ids, gi)
            names = {r["id"]: r["name"] for r in rot}
            pairing = {"server": names[srv], "receiver": names[rec], "sitter": names[sit],
                       "server_id": srv, "receiver_id": rec, "sitter_id": sit}
        v["tally"] = [{"id": r["id"], "name": r["name"], "wins": tally[r["id"]]} for r in rot]
        v["game_no"] = gi
        v["pairing"] = pairing
        return v

    # singles/doubles: prefer point reconstruction when point logs exist
    pts = con.execute("SELECT winner_side FROM point_logs WHERE match_id=? ORDER BY seq", (mid,)).fetchall()
    if pts:
        sc = scoring.score_points([p["winner_side"] for p in pts])
        sets = list(sc["sets"])
        if sc["cur_games"] != (0, 0) or sc["points"] != (0, 0):
            sets.append(sc["cur_games"])
        v["per_point"] = True
        v["point_score"] = scoring.point_display(sc["points"], sc["is_tiebreak"])
        v["is_tiebreak"] = sc["is_tiebreak"]
        s1_ids = [p["id"] for p in s1]
        order = scoring._serve_order(s1_ids, [p["id"] for p in s2], m["kind"])
        gi = len(sc["games"])
        server = (scoring.singles_server(order, gi) if m["kind"] == "singles"
                  else scoring.doubles_server(order, gi))
        names = {r["player_id"]: r["name"] for r in mps}
        v["server"] = names.get(server)
        v["server_id"] = server
    else:
        v["per_point"] = False
        sets = [(s["games_side1"], s["games_side2"]) for s in db.match_sets(con, mid)]
    v["sets"] = [{"g1": a, "g2": b, "won1": a > b, "won2": b > a} for a, b in sets]
    # winner (finished/rating states)
    if m["kind"] != "tt":
        result1, _ = ratings.match_outcome([(s["g1"], s["g2"]) for s in v["sets"]])
        v["winner_side"] = 1 if result1 == 1.0 else (2 if result1 == 0.0 else 0)
    return v


def leaderboard_rows(con, group_id, mode, group_name=None):
    st = db.rating_state(con, group_id)
    live_ids = live_player_ids(con, group_id)
    rows = []
    for p in db.players_of(con, group_id):
        n = st[mode + "_n"].get(p["id"], 0)
        rows.append({
            "id": p["id"], "name": p["name"],
            "rating": round(st[mode].get(p["id"], START)),
            "n": n, "provisional": n < ratings.MIN_MATCHES,
            "live": p["id"] in live_ids,
            "group": group_name,
        })
    return rows


def ranked_and_provisional(rows):
    ranked = sorted([r for r in rows if not r["provisional"]], key=lambda r: -r["rating"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    prov = sorted([r for r in rows if r["provisional"]], key=lambda r: -r["rating"])
    return ranked, prov


def public_groups(con, exclude_id=None):
    return [g for g in con.execute("SELECT * FROM groups WHERE is_public=1").fetchall()
            if g["id"] != exclude_id]


# --- landing --------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", {})


@app.post("/api/group/create")
async def api_create_group(request: Request):
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, 400)
    con = get_con()
    gid, code = db.create_group(con, name)
    con.close()
    return {"code": code, "name": name}


@app.post("/api/group/join")
async def api_join_group(request: Request):
    data = await request.json()
    con = get_con()
    g = db.group_by_code(con, data.get("code", ""))
    con.close()
    if not g:
        return JSONResponse({"error": "no group with that code"}, 404)
    return {"code": g["code"], "name": g["name"]}


# --- tab pages ------------------------------------------------------------
def _page(request, code, tab, extra=None):
    con = get_con()
    g = require_group(con, code)
    ctx = {"request": request, "g": dict(g), "tab": tab, "code": code}
    if extra:
        ctx.update(extra(con, g))
    con.close()
    return templates.TemplateResponse(request, f"{tab}.html", ctx)


@app.get("/g/{code}", response_class=HTMLResponse)
def group_home(code: str):
    return RedirectResponse(f"/g/{code}/live")


@app.get("/g/{code}/live", response_class=HTMLResponse)
def page_live(request: Request, code: str):
    return _page(request, code, "live")


@app.get("/g/{code}/leaderboard", response_class=HTMLResponse)
def page_leaderboard(request: Request, code: str):
    return _page(request, code, "leaderboard")


@app.get("/g/{code}/log", response_class=HTMLResponse)
def page_log(request: Request, code: str):
    def extra(con, g):
        return {"players": [dict(p) for p in db.players_of(con, g["id"])]}
    return _page(request, code, "log", extra)


@app.get("/g/{code}/groups", response_class=HTMLResponse)
def page_groups(request: Request, code: str):
    def extra(con, g):
        return {"players": [dict(p) for p in db.players_of(con, g["id"])]}
    return _page(request, code, "groups", extra)


@app.get("/g/{code}/history", response_class=HTMLResponse)
def page_history(request: Request, code: str):
    return _page(request, code, "history")


@app.get("/g/{code}/player/{pid}", response_class=HTMLResponse)
def page_player(request: Request, code: str, pid: int):
    con = get_con()
    g = require_group(con, code)
    p = con.execute("SELECT * FROM players WHERE id=? AND group_id=?", (pid, g["id"])).fetchone()
    if not p:
        con.close()
        raise HTTPException(404, "player not found")
    data = player_payload(con, g, pid)
    con.close()
    return templates.TemplateResponse(request, "player.html",
                                      {"g": dict(g), "code": code,
                                       "tab": "leaderboard", "p": data})


# --- read JSON (polled every 3s by live views) ----------------------------
@app.get("/g/{code}/api/live")
def api_live(code: str):
    con = get_con()
    g = require_group(con, code)
    live = con.execute("SELECT * FROM matches WHERE group_id=? AND status='live' AND deleted=0 "
                       "ORDER BY id DESC", (g["id"],)).fetchall()
    out = {"matches": [match_view(con, m) for m in live], "public": []}
    for pg in public_groups(con, exclude_id=g["id"]):
        pm = con.execute("SELECT * FROM matches WHERE group_id=? AND status='live' AND deleted=0",
                         (pg["id"],)).fetchall()
        for m in pm:
            mv = match_view(con, m)
            mv["group"] = pg["name"]
            out["public"].append(mv)
    con.close()
    return out


@app.get("/g/{code}/api/match/{mid}")
def api_match(code: str, mid: int):
    con = get_con()
    g = require_group(con, code)
    m = db.match_row(con, mid)
    if not m or m["group_id"] != g["id"]:
        con.close()
        raise HTTPException(404)
    v = match_view(con, m)
    con.close()
    return v


@app.get("/g/{code}/api/leaderboard")
def api_leaderboard(code: str, scope: str = "group", mode: str = "singles"):
    con = get_con()
    g = require_group(con, code)
    if scope == "everyone":
        rows = []
        for pg in public_groups(con):
            rows += leaderboard_rows(con, pg["id"], mode, group_name=pg["name"])
    else:
        rows = leaderboard_rows(con, g["id"], mode)
    ranked, prov = ranked_and_provisional(rows)
    con.close()
    return {"ranked": ranked, "provisional": prov, "scope": scope, "mode": mode}


@app.get("/g/{code}/api/history")
def api_history(code: str):
    con = get_con()
    g = require_group(con, code)
    rows = con.execute(
        "SELECT * FROM matches WHERE group_id=? AND status='finished' AND deleted=0 "
        "ORDER BY COALESCE(finished_at, created_at) DESC, id DESC", (g["id"],)
    ).fetchall()
    done = []
    for m in rows:
        v = match_view(con, m)
        v["voided"] = bool(m["voided"])
        v["story"] = scoring.match_story(con, m["id"]) if v.get("per_point") else None
        done.append(v)
    con.close()
    # v2: no approval/delete request cards — finished results are immediate.
    return {"requests": [], "matches": done}


# --- write actions (having the code = member) -----------------------------
async def _body(request):
    try:
        return await request.json()
    except Exception:
        return {}


@app.post("/g/{code}/api/public")
async def api_set_public(code: str, request: Request):
    d = await _body(request)
    con = get_con()
    g = require_group(con, code)
    db.set_public(con, g["id"], bool(d.get("is_public")))
    con.close()
    return {"is_public": bool(d.get("is_public"))}


@app.post("/g/{code}/api/player")
async def api_add_player(code: str, request: Request):
    d = await _body(request)
    con = get_con()
    g = require_group(con, code)
    try:
        pid = db.add_player(con, g["id"], d.get("name", ""))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"id": pid, "name": d["name"].strip()}


@app.post("/g/{code}/api/match/start")
async def api_start(code: str, request: Request):
    d = await _body(request)
    con = get_con()
    g = require_group(con, code)
    mid = logic.start_match(con, g["id"], d["kind"], d.get("side1", []), d.get("side2", []),
                            d.get("rotation", []), d.get("logger"))
    con.close()
    return {"id": mid}


@app.post("/g/{code}/api/played")
async def api_played(code: str, request: Request):
    d = await _body(request)
    con = get_con()
    g = require_group(con, code)
    try:
        mid = logic.save_played(con, g["id"], d["kind"], d.get("side1", []), d.get("side2", []),
                                d.get("rotation", []), d.get("sets", []), d.get("logger"),
                                d.get("played_on"))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"id": mid}


@app.post("/g/{code}/api/match/{mid}/sets")
async def api_sets(code: str, mid: int, request: Request):
    d = await _body(request)
    con = get_con()
    require_group(con, code)
    try:
        logic.edit_sets(con, mid, [(int(a), int(b)) for a, b in d.get("sets", [])])
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"ok": True}


@app.post("/g/{code}/api/match/{mid}/point")
async def api_point(code: str, mid: int, request: Request):
    d = await _body(request)
    con = get_con()
    require_group(con, code)
    logic.log_point(con, mid, int(d["winner_side"]), d.get("server"))
    pts = con.execute("SELECT winner_side FROM point_logs WHERE match_id=? ORDER BY seq", (mid,)).fetchall()
    logic._write_sets(con, mid, scoring.all_sets_for_storage([p["winner_side"] for p in pts]))
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/g/{code}/api/match/{mid}/point/undo")
async def api_point_undo(code: str, mid: int):
    con = get_con()
    require_group(con, code)
    row = con.execute("SELECT MAX(seq) s FROM point_logs WHERE match_id=?", (mid,)).fetchone()
    if row and row["s"]:
        con.execute("DELETE FROM point_logs WHERE match_id=? AND seq=?", (mid, row["s"]))
        con.commit()
    pts = con.execute("SELECT winner_side FROM point_logs WHERE match_id=? ORDER BY seq", (mid,)).fetchall()
    logic._write_sets(con, mid, scoring.all_sets_for_storage([p["winner_side"] for p in pts]))
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/g/{code}/api/match/{mid}/tt")
async def api_tt(code: str, mid: int, request: Request):
    d = await _body(request)
    con = get_con()
    require_group(con, code)
    logic.log_tt_game(con, mid, d.get("server"), int(d["winner"]))
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/g/{code}/api/match/{mid}/tt/undo")
async def api_tt_undo(code: str, mid: int):
    con = get_con()
    require_group(con, code)
    logic.undo_tt_game(con, mid)
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/g/{code}/api/match/{mid}/finish")
async def api_finish(code: str, mid: int, request: Request):
    await _body(request)
    con = get_con()
    require_group(con, code)
    try:
        logic.finish_match(con, mid)   # v2: finished + rated immediately
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    status = db.match_row(con, mid)["status"]
    con.close()
    return {"status": status}


@app.post("/g/{code}/api/match/{mid}/delete")
async def api_delete(code: str, mid: int, request: Request):
    await _body(request)
    con = get_con()
    require_group(con, code)
    try:
        res = logic.delete_match(con, mid)   # v2: immediate soft-delete
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"result": res}


# --- player page payload --------------------------------------------------
def player_payload(con, g, pid):
    st = db.rating_state(con, g["id"])
    p = con.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
    live_ids = live_player_ids(con, g["id"])
    # pair ratings for this player
    pairs = []
    names = {r["id"]: r["name"] for r in db.players_of(con, g["id"])}
    for (a, b), rating in st["pairs"].items():
        if pid in (a, b):
            partner = b if a == pid else a
            n = st["pairs_n"][(a, b)]
            pairs.append({"partner": names.get(partner, "?"), "rating": round(rating),
                          "n": n, "provisional": n < ratings.PAIR_PROVISIONAL})
    # match history + last5
    hist = []
    last5 = []
    ms = con.execute(
        "SELECT m.* FROM matches m JOIN match_players mp ON mp.match_id=m.id "
        "WHERE mp.player_id=? AND m.status='finished' AND m.voided=0 AND m.deleted=0 "
        "ORDER BY COALESCE(m.finished_at,m.created_at) DESC, m.id DESC", (pid,)
    ).fetchall()
    wins = losses = 0
    for m in ms:
        v = match_view(con, m)
        if m["kind"] != "tt":
            s1_ids = [x["id"] for x in v["side1"]]
            my_side = 1 if pid in s1_ids else 2
            won = v.get("winner_side") == my_side
        else:
            tally = {t["id"]: t["wins"] for t in v["tally"]}
            best = max(tally.values()) if tally else 0
            won = tally.get(pid, 0) == best and best > 0
        if won:
            wins += 1
        else:
            losses += 1
        if len(last5) < 5:
            last5.append("W" if won else "L")
        hist.append(v)
    return {
        "id": pid, "name": p["name"],
        "singles": round(st["singles"].get(pid, START)),
        "singles_n": st["singles_n"].get(pid, 0),
        "singles_prov": st["singles_n"].get(pid, 0) < ratings.MIN_MATCHES,
        "doubles": round(st["doubles"].get(pid, START)),
        "doubles_n": st["doubles_n"].get(pid, 0),
        "doubles_prov": st["doubles_n"].get(pid, 0) < ratings.MIN_MATCHES,
        "pairs": pairs, "wins": wins, "losses": losses, "last5": last5,
        "live": pid in live_ids, "matches": hist,
        "serve": scoring.serve_return_stats(con, g["id"], pid),
    }


@app.get("/api/global/leaderboard")
def api_global_leaderboard(mode: str = "singles"):
    con = get_con()
    rows = []
    for pg in public_groups(con):
        rows += leaderboard_rows(con, pg["id"], mode, group_name=pg["name"])
    ranked, prov = ranked_and_provisional(rows)
    con.close()
    return {"ranked": ranked, "provisional": prov}


# ==========================================================================
# ADMIN GOD-MODE — one secret key, no link anywhere in the user-facing app.
# ==========================================================================
def require_admin(request: Request):
    """Gate every admin endpoint. Wrong/missing key -> generic 404 (reveals nothing)."""
    key = request.headers.get("x-admin-key") or request.query_params.get("key") or ""
    if not key or key != ADMIN_KEY:
        raise HTTPException(404, "Not Found")


async def _admin_body(request: Request):
    require_admin(request)
    try:
        return await request.json()
    except Exception:
        return {}


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    # The shell is inert without the key; all data endpoints enforce it.
    return templates.TemplateResponse(request, "admin.html", {})


def _group_card(con, g):
    gid = g["id"]
    players = con.execute("SELECT COUNT(*) c FROM players WHERE group_id=?", (gid,)).fetchone()["c"]
    matches = con.execute("SELECT COUNT(*) c FROM matches WHERE group_id=? AND deleted=0", (gid,)).fetchone()["c"]
    live = con.execute("SELECT COUNT(*) c FROM matches WHERE group_id=? AND status='live' AND deleted=0", (gid,)).fetchone()["c"]
    last = con.execute(
        "SELECT MAX(COALESCE(finished_at, started_at, created_at)) t FROM matches WHERE group_id=?",
        (gid,)).fetchone()["t"]
    return {"id": gid, "name": g["name"], "code": g["code"], "is_public": bool(g["is_public"]),
            "players": players, "matches": matches, "live": live,
            "created_at": g["created_at"], "last_activity": last}


@app.get("/admin/api/dashboard")
def admin_dashboard(request: Request):
    require_admin(request)
    con = get_con()
    groups = [_group_card(con, g) for g in db.all_groups(con)]
    totals = {
        "groups": con.execute("SELECT COUNT(*) c FROM groups").fetchone()["c"],
        "players": con.execute("SELECT COUNT(*) c FROM players").fetchone()["c"],
        "matches": con.execute("SELECT COUNT(*) c FROM matches WHERE deleted=0").fetchone()["c"],
        "live": con.execute("SELECT COUNT(*) c FROM matches WHERE status='live' AND deleted=0").fetchone()["c"],
    }
    logs = [{"at": r["at"], "action": r["action"], "target": r["target"]} for r in db.admin_logs(con)]
    con.close()
    return {"totals": totals, "groups": groups, "log": logs}


@app.get("/admin/api/group/{gid}")
def admin_group_detail(request: Request, gid: int):
    require_admin(request)
    con = get_con()
    g = db.group_by_id(con, gid)
    if not g:
        con.close()
        raise HTTPException(404, "Not Found")
    players = [{"id": p["id"], "name": p["name"]} for p in db.players_of(con, gid)]
    ms = con.execute(
        "SELECT * FROM matches WHERE group_id=? ORDER BY COALESCE(finished_at, created_at) DESC, id DESC",
        (gid,)).fetchall()
    matches = []
    for m in ms:
        v = match_view(con, m)
        v["voided"] = bool(m["voided"])
        v["deleted"] = bool(m["deleted"])
        matches.append(v)
    card = _group_card(con, g)
    con.close()
    return {"group": card, "players": players, "matches": matches}


def _admin_ok(con, action, target):
    db.log_admin(con, action, target)
    con.close()
    return {"ok": True}


@app.post("/admin/api/group/create")
async def admin_group_create(request: Request):
    d = await _admin_body(request)
    name = (d.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, 400)
    con = get_con()
    gid, code = db.create_group(con, name)
    db.log_admin(con, "group.create", f"{name} [{code}]")
    con.close()
    return {"id": gid, "code": code, "name": name}


@app.post("/admin/api/group/{gid}/public")
async def admin_group_public(request: Request, gid: int):
    d = await _admin_body(request)
    con = get_con()
    db.set_public(con, gid, bool(d.get("is_public")))
    return _admin_ok(con, "group.public", f"gid={gid} -> {bool(d.get('is_public'))}")


@app.post("/admin/api/group/{gid}/regen")
async def admin_group_regen(request: Request, gid: int):
    await _admin_body(request)
    con = get_con()
    g = db.group_by_id(con, gid)
    if not g:
        con.close()
        raise HTTPException(404, "Not Found")
    old = g["code"]
    code = db.regen_code(con, gid)
    db.log_admin(con, "group.regen_code", f"gid={gid} {old} -> {code}")
    con.close()
    return {"code": code}


@app.post("/admin/api/group/{gid}/rename")
async def admin_group_rename(request: Request, gid: int):
    d = await _admin_body(request)
    con = get_con()
    try:
        db.rename_group(con, gid, d.get("name", ""))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    return _admin_ok(con, "group.rename", f"gid={gid} -> {d.get('name')}")


@app.post("/admin/api/group/{gid}/delete")
async def admin_group_delete(request: Request, gid: int):
    d = await _admin_body(request)
    con = get_con()
    g = db.group_by_id(con, gid)
    if not g:
        con.close()
        raise HTTPException(404, "Not Found")
    if (d.get("confirm") or "").strip() != g["name"]:
        con.close()
        return JSONResponse({"error": "type the exact group name to confirm"}, 400)
    db.delete_group(con, gid)
    return _admin_ok(con, "group.delete", f"gid={gid} [{g['name']}]")


@app.post("/admin/api/player/{pid}/rename")
async def admin_player_rename(request: Request, pid: int):
    d = await _admin_body(request)
    con = get_con()
    try:
        db.rename_player(con, pid, d.get("name", ""))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    return _admin_ok(con, "player.rename", f"pid={pid} -> {d.get('name')}")


@app.post("/admin/api/player/{pid}/delete")
async def admin_player_delete(request: Request, pid: int):
    d = await _admin_body(request)
    con = get_con()
    p = db.player_row(con, pid)
    if not p:
        con.close()
        raise HTTPException(404, "Not Found")
    if (d.get("confirm") or "").strip() != p["name"]:
        con.close()
        return JSONResponse({"error": "type the exact player name to confirm"}, 400)
    db.delete_player(con, pid)
    return _admin_ok(con, "player.delete", f"pid={pid} [{p['name']}]")


@app.post("/admin/api/match/{mid}/edit")
async def admin_match_edit(request: Request, mid: int):
    d = await _admin_body(request)
    con = get_con()
    try:
        logic.admin_edit_match(con, mid, sets=d.get("sets"), played_on=d.get("played_on"),
                               kind=d.get("kind"))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    return _admin_ok(con, "match.edit", f"mid={mid}")


@app.post("/admin/api/match/{mid}/delete")
async def admin_match_delete(request: Request, mid: int):
    await _admin_body(request)
    con = get_con()
    try:
        logic.admin_delete_match(con, mid)
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    return _admin_ok(con, "match.delete", f"mid={mid}")


@app.post("/admin/api/match/{mid}/void")
async def admin_match_void(request: Request, mid: int):
    await _admin_body(request)
    con = get_con()
    try:
        logic.admin_void_match(con, mid)
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    return _admin_ok(con, "match.void", f"mid={mid}")


@app.post("/admin/api/match/{mid}/unvoid")
async def admin_match_unvoid(request: Request, mid: int):
    await _admin_body(request)
    con = get_con()
    try:
        logic.admin_unvoid_match(con, mid)
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    return _admin_ok(con, "match.unvoid", f"mid={mid}")


@app.post("/admin/api/match/{mid}/restore")
async def admin_match_restore(request: Request, mid: int):
    await _admin_body(request)
    con = get_con()
    try:
        logic.admin_restore_match(con, mid)
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    return _admin_ok(con, "match.restore", f"mid={mid}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
