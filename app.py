"""Rally — tennis scorer. CLEAN FOUNDATION (global uuid identity, groups optional).

Identity is the auth token alone (players.id = auth.users.id). A group is only ever a FILTER
(?group=<code>); no group = everything the signed-in player has. Writes require a signed-in user
with a player row. Admin god-mode is behind one secret ADMIN_KEY.
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
import auth
import auth_playerid
from ratings import START

BASE = Path(__file__).parent
app = FastAPI(title="Rally")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _asset_version():
    import hashlib
    h = hashlib.md5()
    for f in ("app.js", "auth.js", "engine.js", "sync.js", "log.js", "style.css"):
        p = BASE / "static" / f
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


ASSET_V = _asset_version()
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals["v"] = ASSET_V

db.init_db()   # verifies (PG) or builds (SQLite) the clean schema; FAILS LOUD if unmigrated


def _load_admin_key():
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
    return db.connect()


def current_user(request: Request):
    return auth.verify_token(auth.bearer(request))


def require_user(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(401, "sign in required")
    return u


def me_player(con, request):
    """The signed-in user's player row (or None). player id == auth sub."""
    u = current_user(request)
    if not u:
        return None, None
    return u, db.get_player(con, u["sub"])


def require_player(con, request):
    u = require_user(request)
    p = db.get_player(con, u["sub"])
    if not p:
        raise HTTPException(409, "set up your player first")
    return u, p


def _gid_from_query(con, request):
    """Optional ?group=<code> -> group id, or None (= everything)."""
    code = request.query_params.get("group")
    if not code:
        return None
    g = db.group_by_code(con, code)
    return g["id"] if g else None


def _my_group_ids(con, pid):
    return [g["id"] for g in db.groups_of_player(con, pid)]


def live_player_ids(con):
    rows = con.execute(
        "SELECT DISTINCT mp.player_id FROM match_players mp JOIN matches m ON m.id=mp.match_id "
        "WHERE m.status='live'").fetchall()
    return {r["player_id"] for r in rows}


def match_view(con, m):
    mid = m["id"]
    mps = db.match_players(con, mid)
    s1 = [{"id": r["player_id"], "name": r["name"], "real_name": r["real_name"]} for r in mps if r["side"] == 1]
    s2 = [{"id": r["player_id"], "name": r["name"], "real_name": r["real_name"]} for r in mps if r["side"] == 2]
    rot = [{"id": r["player_id"], "name": r["name"], "real_name": r["real_name"], "pos": r["rotation_pos"]}
           for r in mps if r["rotation_pos"]]
    rot.sort(key=lambda x: x["pos"])
    played_on = (m["finished_at"] or m["started_at"] or m["created_at"] or "")
    v = {"id": mid, "kind": m["kind"], "status": m["status"], "played_on": played_on,
         "started_at": m["started_at"], "group_id": m["group_id"],
         "former_group_name": m["former_group_name"], "side1": s1, "side2": s2, "rotation": rot}

    if m["kind"] == "tt":
        games = db.tt_games(con, mid)
        tally = {r["id"]: 0 for r in rot}
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
        v["tally"] = [{"id": r["id"], "name": r["name"], "real_name": r["real_name"], "wins": tally[r["id"]]} for r in rot]
        v["game_no"] = gi
        v["pairing"] = pairing
        v["tt_games"] = [{"server": gm["server_player_id"],
                          "receiver": gm["receiver_player_id"], "winner": gm["winner_player_id"]} for gm in games]
        return v

    pts = con.execute("SELECT winner_side FROM point_logs WHERE match_id=? ORDER BY seq", (mid,)).fetchall()
    if pts:
        v["points"] = [p["winner_side"] for p in pts]
        sc = scoring.score_points([p["winner_side"] for p in pts])
        sets = list(sc["sets"])
        if sc["cur_games"] != (0, 0) or sc["points"] != (0, 0):
            sets.append(sc["cur_games"])
        v["per_point"] = True
        v["point_score"] = scoring.point_display(sc["points"], sc["is_tiebreak"])
        v["is_tiebreak"] = sc["is_tiebreak"]
        order = scoring._serve_order([p["id"] for p in s1], [p["id"] for p in s2], m["kind"])
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
    if m["kind"] != "tt":
        result1, _ = ratings.match_outcome([(s["g1"], s["g2"]) for s in v["sets"]])
        v["winner_side"] = 1 if result1 == 1.0 else (2 if result1 == 0.0 else 0)
    return v


def win_prob_for(state, v):
    def avg(ids, mode):
        return sum(state[mode].get(i, START) for i in ids) / len(ids)
    if v["kind"] == "tt":
        rot = v.get("rotation", [])
        weights = [10 ** (state["singles"].get(r["id"], START) / 400.0) for r in rot]
        tot = sum(weights) or 1.0
        return [{"label": r["name"], "pct": round(100 * weights[i] / tot)} for i, r in enumerate(rot)]
    s1 = [p["id"] for p in v["side1"]]
    s2 = [p["id"] for p in v["side2"]]
    n1 = " & ".join(p["name"] for p in v["side1"])
    n2 = " & ".join(p["name"] for p in v["side2"])
    if not s1 or not s2:
        return []
    if v["kind"] == "doubles" and len(s1) == 2 and len(s2) == 2:
        p1, p2 = ratings.canon(*s1), ratings.canon(*s2)
        if state["pairs_n"].get(p1, 0) >= 3 and state["pairs_n"].get(p2, 0) >= 3:
            ra, rb = state["pairs"].get(p1, START), state["pairs"].get(p2, START)
        else:
            ra, rb = avg(s1, "doubles"), avg(s2, "doubles")
    else:
        ra, rb = avg(s1, "singles"), avg(s2, "singles")
    pa = round(100 * ratings.expected(ra, rb))
    return [{"label": n1, "pct": pa}, {"label": n2, "pct": 100 - pa}]


def _pblock(p):
    return {"id": p["id"], "name": p["game_name"], "real_name": p["real_name"], "code": p["code"]}


def _rel_from_map(fmap, me_pid, other_id):
    """ME's standing relationship to a player: you / friend / sent / incoming / none.
    Reads a prefetched friend_map instead of querying per player (see db.friend_map)."""
    if me_pid and me_pid == other_id:
        return "you"
    if not me_pid:
        return "none"
    f = fmap.get(other_id)
    if not f:
        return "none"
    if f["status"] == "accepted":
        return "friend"
    return "sent" if f["requested_by"] == me_pid else "incoming"


def _relationship(con, me_pid, other_id):
    """Single-player form of _rel_from_map (one query). Use the map form for lists."""
    if not me_pid or me_pid == other_id:
        return _rel_from_map({}, me_pid, other_id)
    f = db.friendship(con, me_pid, other_id)
    return _rel_from_map({other_id: f} if f else {}, me_pid, other_id)


def leaderboard_rows(con, group_id, mode, me_pid=None):
    st = db.rating_state(con, group_id)
    live_ids = live_player_ids(con)
    if group_id:
        players = db.members_of(con, group_id)
    else:
        players = con.execute("SELECT * FROM players ORDER BY LOWER(game_name)").fetchall()
    # One friendships query for the whole board, not one per row.
    fmap = db.friend_map(con, me_pid) if me_pid else {}
    rows = []
    for p in players:
        n = st[mode + "_n"].get(p["id"], 0)
        rows.append({"id": p["id"], "name": p["game_name"], "real_name": p["real_name"],
                     "code": p["code"], "rel": _rel_from_map(fmap, me_pid, p["id"]),
                     "rating": round(st[mode].get(p["id"], START)), "n": n,
                     "provisional": n < ratings.MIN_MATCHES, "live": p["id"] in live_ids, "group": None})
    return rows


def ranked_and_provisional(rows):
    ranked = sorted([r for r in rows if not r["provisional"]], key=lambda r: -r["rating"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    prov = sorted([r for r in rows if r["provisional"]], key=lambda r: -r["rating"])
    return ranked, prov


def leaderboard_payload(rows, gid, mode):
    """ONE list, in display order: ranked players (5+ matches, numbered) then under-5 players
    (unnumbered, greyed inline by the client). `ranked`/`provisional` are kept as views of the
    same rows so nothing that reads them breaks — but `rows` is the list the UI renders."""
    ranked, prov = ranked_and_provisional(rows)
    return {"rows": ranked + prov, "ranked": ranked, "provisional": prov,
            "scope": "group" if gid else "everyone", "mode": mode}


# --- auth endpoints -------------------------------------------------------
@app.get("/api/auth/config")
def api_auth_config():
    return auth.client_config()


@app.post("/api/auth/email/start")
async def api_auth_email_start(request: Request):
    d = await request.json()
    return auth.start_email_otp(d.get("email", ""))


@app.post("/api/auth/email/verify")
async def api_auth_email_verify(request: Request):
    d = await request.json()
    r = auth.verify_email_otp(d.get("email", ""), d.get("code", ""))
    return JSONResponse(r, 401) if "error" in r else r


@app.post("/api/auth/google")
async def api_auth_google(request: Request):
    if auth.AUTH_MODE != "mock":
        return JSONResponse({"error": "use client-side Google OAuth in supabase mode",
                             "config": auth.client_config()}, 400)
    d = await request.json()
    return auth.google_mock(d.get("email") or "tester@gmail.com")


@app.post("/api/auth/guest")
async def api_auth_guest(request: Request):
    if auth.AUTH_MODE != "mock":
        return JSONResponse({"error": "guest sign-in is disabled"}, 400)
    d = await request.json()
    did = (d.get("device_id") or "").strip()
    if not did:
        return JSONResponse({"error": "device_id required"}, 400)
    return {"token": auth.mint_mock_token("guest:" + did, None)}


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    u = current_user(request)
    return {"signed_in": bool(u), "email": u.get("email") if u else None,
            "name": u.get("name") if u else None}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?"))


@app.post("/api/auth/player-id")
async def api_player_id_signin(request: Request):
    d = await request.json()
    con = get_con()
    try:
        status, body = auth_playerid.player_signin(con, d.get("player_id"), d.get("password"), _client_ip(request))
    finally:
        con.close()
    return JSONResponse(body, status)


@app.post("/api/auth/set-password")
async def api_set_password(request: Request):
    d = await request.json()
    u = current_user(request)
    if not u:
        return JSONResponse({"error": "sign in first"}, 401)
    con = get_con()
    try:
        status, body = auth_playerid.do_set_password(con, u["sub"], d.get("password") or "", auth.bearer(request))
    finally:
        con.close()
    return JSONResponse(body, status)


# --- identity (global) ----------------------------------------------------
@app.get("/api/me")
def api_me(request: Request):
    """Resolve the player from the auth token alone. First sign-in with no player -> needs_name."""
    con = get_con()
    u, p = me_player(con, request)
    con.close()
    if not u:
        return {"signed_in": False, "player_id": None}
    if not p:
        return {"signed_in": True, "player_id": None, "needs_name": True,
                "email": u.get("email"), "provider_name": u.get("name")}
    return {"signed_in": True, "player_id": p["id"], "player_name": p["game_name"],
            "player_real_name": p["real_name"], "code": p["code"], "email": u.get("email")}


@app.post("/api/me/claim")
async def api_me_claim(request: Request):
    d = await _body(request)
    con = get_con()
    u = require_user(request)
    if db.get_player(con, u["sub"]):
        con.close()
        return JSONResponse({"error": "you already have a player"}, 409)
    try:
        code = db.create_player(con, u["sub"], d.get("name", ""), d.get("real_name"))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"player_id": u["sub"], "code": code, "name": (d.get("name") or "").strip()}


@app.post("/api/me/rename")
async def api_me_rename(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    try:
        db.rename_player(con, p["id"], game_name=d.get("name"), real_name=d.get("real_name"))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 409)
    con.close()
    return {"player_id": p["id"]}


# --- SPA shell (served at `/`, `/<tab>`, `/g/<code>/<tab>` for a group filter, `/player/<id>`) ---
def _shell(request, tab, group=None, player=None):
    g = None
    if group:
        con = get_con()
        g = db.group_by_code(con, group)
        con.close()
    return templates.TemplateResponse(request, "shell.html",
                                      {"g": (dict(g) if g else None), "tab": tab, "player": player})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _shell(request, "live")


@app.get("/live", response_class=HTMLResponse)
def page_live0(request: Request):
    return _shell(request, "live")


@app.get("/leaderboard", response_class=HTMLResponse)
def page_ranks0(request: Request):
    return _shell(request, "leaderboard")


@app.get("/log", response_class=HTMLResponse)
def page_log0(request: Request):
    return _shell(request, "log")


@app.get("/groups", response_class=HTMLResponse)
def page_groups0(request: Request):
    return _shell(request, "groups")


@app.get("/history", response_class=HTMLResponse)
def page_history0(request: Request):
    return _shell(request, "history")


@app.get("/player/{pid}", response_class=HTMLResponse)
def page_player0(request: Request, pid: str):
    return _shell(request, "leaderboard", player=pid)


@app.get("/g/{code}", response_class=HTMLResponse)
def group_home(code: str):
    return RedirectResponse(f"/g/{code}/live")


@app.get("/g/{code}/{tab}", response_class=HTMLResponse)
def page_group_tab(request: Request, code: str, tab: str):
    if tab not in ("live", "leaderboard", "log", "groups", "history"):
        tab = "live"
    return _shell(request, tab, group=code)


# --- reads (optional ?group=<code>) ---------------------------------------
async def _body(request):
    try:
        return await request.json()
    except Exception:
        return {}


@app.get("/api/live")
def api_live(request: Request):
    con = get_con()
    gid = _gid_from_query(con, request)
    u, p = me_player(con, request)
    if gid:
        rows = con.execute("SELECT * FROM matches WHERE status='live' AND group_id=? ORDER BY started_at DESC",
                           (gid,)).fetchall()
    elif p:
        gids = _my_group_ids(con, p["id"])
        ph = ",".join("?" for _ in gids)
        q = ("SELECT DISTINCT m.* FROM matches m LEFT JOIN match_players mp ON mp.match_id=m.id "
             "WHERE m.status='live' AND (mp.player_id=?" + (f" OR m.group_id IN ({ph})" if gids else "") + ") "
             "ORDER BY m.started_at DESC")
        rows = con.execute(q, tuple([p["id"]] + gids)).fetchall()
    else:
        rows = []
    # rating_state scans every counted match and rebuilds the whole rating table. It is only
    # needed for win_prob on a live card, so with nothing live it was pure wasted latency —
    # and "nothing live" is the common case on every Live poll.
    st = db.rating_state(con, gid) if rows else None
    mine = []
    for m in rows:
        mv = match_view(con, m)
        mv["win_prob"] = win_prob_for(st, mv)
        mine.append(mv)
    con.close()
    return {"matches": mine, "public": []}


@app.get("/api/meta")
def api_meta(request: Request):
    """Court-picker roster. With ?group= -> that group's members. Without -> the player + their
    ACCEPTED friends only (the rule: the picker reads accepted friendships only)."""
    con = get_con()
    gid = _gid_from_query(con, request)
    u, p = me_player(con, request)
    st = db.rating_state(con, gid)
    live_ids = live_player_ids(con)
    if gid:
        roster = db.members_of(con, gid)
    elif p:
        roster = [p] + list(db.accepted_friends(con, p["id"]))
    else:
        roster = []
    players = []
    for pl in roster:
        players.append({
            "id": pl["id"], "name": pl["game_name"], "real_name": pl["real_name"],
            "live": pl["id"] in live_ids,
            "singles": round(st["singles"].get(pl["id"], START)) - 1200,
            "singles_n": st["singles_n"].get(pl["id"], 0),
            "doubles": round(st["doubles"].get(pl["id"], START)) - 1200,
            "doubles_n": st["doubles_n"].get(pl["id"], 0),
        })
    pairs = {f"{a}_{b}": {"rating": round(r) - 1200, "n": st["pairs_n"][(a, b)]}
             for (a, b), r in st["pairs"].items()}
    con.close()
    return {"players": players, "pairs": pairs, "pair_provisional": ratings.PAIR_PROVISIONAL}


@app.get("/api/leaderboard")
def api_leaderboard(request: Request, mode: str = "singles"):
    con = get_con()
    gid = _gid_from_query(con, request)
    u, p = me_player(con, request)
    rows = leaderboard_rows(con, gid, mode, p["id"] if p else None)
    con.close()
    return leaderboard_payload(rows, gid, mode)


@app.get("/api/history")
def api_history(request: Request):
    con = get_con()
    gid = _gid_from_query(con, request)
    u, p = me_player(con, request)
    shown = "('counted','pending_approval','disputed')"
    if gid:
        rows = con.execute(f"SELECT * FROM matches WHERE group_id=? AND status IN {shown} "
                           "ORDER BY COALESCE(finished_at, created_at) DESC, id DESC", (gid,)).fetchall()
    elif p:
        # No DISTINCT: match_players PK is (match_id, player_id), so a player appears at most once
        # per match — the JOIN yields one row per match already. DISTINCT + an ORDER BY expression
        # not in the select list is a Postgres error (SELECT DISTINCT ... ORDER BY COALESCE(...)),
        # which 500'd the signed-in History path (SQLite allowed it). This was the History hang.
        rows = con.execute(
            f"SELECT m.* FROM matches m JOIN match_players mp ON mp.match_id=m.id "
            f"WHERE mp.player_id=? AND m.status IN {shown} "
            "ORDER BY COALESCE(m.finished_at, m.created_at) DESC, m.id DESC", (p["id"],)).fetchall()
    else:
        rows = []
    done = []
    for m in rows:
        v = match_view(con, m)
        v["story"] = scoring.match_story(con, m["id"]) if v.get("per_point") else None
        if m["former_group_name"]:
            v["group"] = m["former_group_name"]
        done.append(v)
    con.close()
    return {"requests": [], "matches": done}


@app.get("/api/match/{mid}")
def api_match(mid: str):
    con = get_con()
    m = db.match_row(con, mid)
    if not m:
        con.close()
        raise HTTPException(404)
    v = match_view(con, m)
    con.close()
    return v


@app.get("/api/player/{pid}")
def api_player(pid: str, request: Request):
    con = get_con()
    gid = _gid_from_query(con, request)
    if not db.get_player(con, pid):
        con.close()
        raise HTTPException(404, "player not found")
    data = player_payload(con, gid, pid)
    con.close()
    return data


def player_payload(con, gid, pid):
    st = db.rating_state(con, gid)
    p = db.get_player(con, pid)
    live_ids = live_player_ids(con)
    names = {r["id"]: r["game_name"] for r in con.execute("SELECT id, game_name FROM players").fetchall()}
    pairs = []
    for (a, b), rating in st["pairs"].items():
        if pid in (a, b):
            partner = b if a == pid else a
            n = st["pairs_n"][(a, b)]
            pairs.append({"partner": names.get(partner, "?"), "rating": round(rating), "n": n,
                          "provisional": n < ratings.PAIR_PROVISIONAL})
    hist, last5, wins, losses = [], [], 0, 0
    where_g = "AND m.group_id=?" if gid else ""
    params = [pid] + ([gid] if gid else [])
    ms = con.execute(
        f"SELECT m.* FROM matches m JOIN match_players mp ON mp.match_id=m.id "
        f"WHERE mp.player_id=? AND m.status='counted' {where_g} "
        "ORDER BY COALESCE(m.finished_at,m.created_at) DESC, m.id DESC", tuple(params)).fetchall()
    for m in ms:
        v = match_view(con, m)
        if m["kind"] != "tt":
            won = v.get("winner_side") == (1 if pid in [x["id"] for x in v["side1"]] else 2)
        else:
            tally = {t["id"]: t["wins"] for t in v["tally"]}
            best = max(tally.values()) if tally else 0
            won = tally.get(pid, 0) == best and best > 0
        wins, losses = (wins + 1, losses) if won else (wins, losses + 1)
        if len(last5) < 5:
            last5.append("W" if won else "L")
        hist.append(v)
    return {"id": pid, "name": p["game_name"], "real_name": p["real_name"],
            "singles": round(st["singles"].get(pid, START)), "singles_n": st["singles_n"].get(pid, 0),
            "singles_prov": st["singles_n"].get(pid, 0) < ratings.MIN_MATCHES,
            "doubles": round(st["doubles"].get(pid, START)), "doubles_n": st["doubles_n"].get(pid, 0),
            "doubles_prov": st["doubles_n"].get(pid, 0) < ratings.MIN_MATCHES,
            "pairs": pairs, "wins": wins, "losses": losses, "last5": last5,
            "live": pid in live_ids, "matches": hist,
            "serve": scoring.serve_return_stats(con, gid, pid)}


# --- scoring writes (player id = the signed-in user) ----------------------
@app.post("/api/match/start")
async def api_start(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    gid = _gid_from_query(con, request) or (db.group_by_code(con, d["group"])["id"] if d.get("group") else None)
    try:
        mid = logic.start_match(con, gid, d["kind"], d.get("side1", []), d.get("side2", []),
                                d.get("rotation", []), p["id"])
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"id": mid}


@app.post("/api/played")
async def api_played(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    gid = db.group_by_code(con, d["group"])["id"] if d.get("group") else None
    try:
        mid = logic.save_played(con, gid, d["kind"], d.get("side1", []), d.get("side2", []),
                                d.get("rotation", []), d.get("sets", []), p["id"], d.get("played_on"))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"id": mid}


@app.post("/api/match/{mid}/sets")
async def api_sets(mid: str, request: Request):
    d = await _body(request)
    con = get_con()
    require_player(con, request)
    try:
        logic.edit_sets(con, mid, [(int(a), int(b)) for a, b in d.get("sets", [])])
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.execute("DELETE FROM point_logs WHERE match_id=?", (mid,))
    con.commit()
    con.close()
    return {"ok": True}


@app.post("/api/match/{mid}/point")
async def api_point(mid: str, request: Request):
    d = await _body(request)
    con = get_con()
    require_player(con, request)
    logic.log_point(con, mid, int(d["winner_side"]), d.get("server"))
    pts = con.execute("SELECT winner_side FROM point_logs WHERE match_id=? ORDER BY seq", (mid,)).fetchall()
    logic._write_sets(con, mid, scoring.all_sets_for_storage([p["winner_side"] for p in pts]))
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/api/match/{mid}/point/undo")
async def api_point_undo(mid: str, request: Request):
    con = get_con()
    require_player(con, request)
    logic.undo_point(con, mid)
    pts = con.execute("SELECT winner_side FROM point_logs WHERE match_id=? ORDER BY seq", (mid,)).fetchall()
    logic._write_sets(con, mid, scoring.all_sets_for_storage([p["winner_side"] for p in pts]))
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/api/match/{mid}/tt")
async def api_tt(mid: str, request: Request):
    d = await _body(request)
    con = get_con()
    require_player(con, request)
    logic.log_tt_game(con, mid, d.get("server"), d["winner"], d.get("receiver"))
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/api/match/{mid}/tt/undo")
async def api_tt_undo(mid: str, request: Request):
    con = get_con()
    require_player(con, request)
    logic.undo_tt_game(con, mid)
    v = match_view(con, db.match_row(con, mid))
    con.close()
    return v


@app.post("/api/match/{mid}/date")
async def api_match_date(mid: str, request: Request):
    d = await _body(request)
    con = get_con()
    require_player(con, request)
    played = (d.get("played_on") or "").strip()
    if played:
        con.execute("UPDATE matches SET finished_at=? WHERE id=?", (played, mid))
        con.commit()
    con.close()
    return {"ok": True}


@app.post("/api/match/{mid}/finish")
async def api_finish(mid: str, request: Request):
    await _body(request)
    con = get_con()
    require_player(con, request)
    try:
        logic.finish_match(con, mid)
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    status = db.match_row(con, mid)["status"]
    con.close()
    return {"status": status}


@app.post("/api/match/{mid}/delete")
async def api_delete(mid: str, request: Request):
    await _body(request)
    con = get_con()
    require_player(con, request)
    try:
        res = logic.delete_match(con, mid)
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"result": res}


# --- approvals / freeze / resume (participant actions) --------------------
def _require_participant(con, request, mid):
    u, p = require_player(con, request)
    if p["id"] not in db.participants(con, mid):
        raise HTTPException(403, "not a participant")
    return p


@app.post("/api/match/{mid}/approve")
async def api_approve(mid: str, request: Request):
    con = get_con()
    p = _require_participant(con, request, mid)
    logic.approve(con, mid, p["id"])
    st = db.match_row(con, mid)["status"]
    con.close()
    return {"status": st}


@app.post("/api/match/{mid}/unapprove")
async def api_unapprove(mid: str, request: Request):
    con = get_con()
    p = _require_participant(con, request, mid)
    logic.unapprove(con, mid, p["id"])
    st = db.match_row(con, mid)["status"]
    con.close()
    return {"status": st}


@app.post("/api/match/{mid}/dispute")
async def api_dispute(mid: str, request: Request):
    d = await _body(request)
    con = get_con()
    p = _require_participant(con, request, mid)
    logic.dispute(con, mid, p["id"], d.get("reason"))
    st = db.match_row(con, mid)["status"]
    con.close()
    return {"status": st}


@app.post("/api/match/{mid}/freeze")
async def api_freeze(mid: str, request: Request):
    con = get_con()
    p = _require_participant(con, request, mid)
    logic.freeze_request(con, mid, p["id"])
    st = db.match_row(con, mid)["status"]
    con.close()
    return {"status": st}


@app.post("/api/match/{mid}/resume")
async def api_resume(mid: str, request: Request):
    con = get_con()
    p = _require_participant(con, request, mid)
    logic.resume_request(con, mid, p["id"])
    st = db.match_row(con, mid)["status"]
    con.close()
    return {"status": st}


# --- friends --------------------------------------------------------------
@app.get("/api/friends")
def api_friends(request: Request):
    con = get_con()
    u, p = me_player(con, request)
    if not p:
        con.close()
        return {"friends": [], "pending": []}
    friends = [_pblock(x) for x in db.accepted_friends(con, p["id"])]
    pending = [_pblock(x) for x in db.pending_friend_requests(con, p["id"])]
    con.close()
    return {"friends": friends, "pending": pending}


@app.post("/api/friend/request")
async def api_friend_request(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    other = db.get_player_by_code(con, d.get("code", "")) if d.get("code") else db.get_player(con, d.get("id"))
    if not other:
        con.close()
        return JSONResponse({"error": "no such player"}, 404)
    try:
        state = db.request_friend(con, p["id"], other["id"])
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"status": state}


@app.post("/api/friend/accept")
async def api_friend_accept(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    db.accept_friend(con, p["id"], d.get("id"))
    con.close()
    return {"ok": True}


@app.post("/api/friend/decline")
async def api_friend_decline(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    db.decline_friend(con, p["id"], d.get("id"))
    con.close()
    return {"ok": True}


@app.get("/api/players/search")
def api_players_search(request: Request, q: str = ""):
    con = get_con()
    rows = [_pblock(x) for x in db.search_players(con, q)]
    con.close()
    return {"players": rows}


# --- groups ---------------------------------------------------------------
@app.get("/api/groups")
def api_groups(request: Request):
    con = get_con()
    u, p = me_player(con, request)
    if not p:
        con.close()
        return {"groups": []}
    out = []
    for g in db.groups_of_player(con, p["id"]):
        out.append({"id": g["id"], "name": g["name"], "code": g["code"],
                    "is_public": bool(g["is_public"]), "is_admin": g["admin_id"] == p["id"]})
    con.close()
    return {"groups": out}


@app.post("/api/group/create")
async def api_group_create(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    name = (d.get("name") or "").strip()
    if not name:
        con.close()
        return JSONResponse({"error": "name required"}, 400)
    gid, code = db.create_group(con, name, p["id"])
    con.close()
    return {"id": gid, "code": code, "name": name}


@app.post("/api/group/join")
async def api_group_join(request: Request):
    d = await _body(request)
    con = get_con()
    u, p = require_player(con, request)
    g = db.group_by_code(con, d.get("code", ""))
    if not g:
        con.close()
        return JSONResponse({"error": "no group with that code"}, 404)
    if g["is_public"]:
        db.add_member(con, g["id"], p["id"])
        con.close()
        return {"joined": True, "code": g["code"], "name": g["name"]}
    db.add_join_request(con, g["id"], p["id"])
    con.close()
    return {"joined": False, "requested": True, "name": g["name"]}


def _require_group_admin(con, request, gid):
    u, p = require_player(con, request)
    g = db.group_by_id(con, gid)
    if not g:
        raise HTTPException(404, "group not found")
    if g["admin_id"] != p["id"]:
        raise HTTPException(403, "only the group admin can do that")
    return p, g


@app.post("/api/group/{gid}/public")
async def api_group_public(gid: str, request: Request):
    d = await _body(request)
    con = get_con()
    _require_group_admin(con, request, gid)
    db.set_public(con, gid, bool(d.get("is_public")))
    con.close()
    return {"is_public": bool(d.get("is_public"))}


@app.post("/api/group/{gid}/rename")
async def api_group_rename(gid: str, request: Request):
    d = await _body(request)
    con = get_con()
    _require_group_admin(con, request, gid)
    try:
        db.rename_group(con, gid, d.get("name", ""))
    except ValueError as e:
        con.close()
        return JSONResponse({"error": str(e)}, 400)
    con.close()
    return {"ok": True}


@app.post("/api/group/{gid}/code")
async def api_group_code(gid: str, request: Request):
    con = get_con()
    _require_group_admin(con, request, gid)
    code = db.regen_group_code(con, gid)
    con.close()
    return {"code": code}


@app.post("/api/group/{gid}/admin")
async def api_group_admin(gid: str, request: Request):
    d = await _body(request)
    con = get_con()
    _require_group_admin(con, request, gid)
    db.set_admin(con, gid, d.get("player_id"))
    con.close()
    return {"ok": True}


@app.post("/api/group/{gid}/remove")
async def api_group_remove(gid: str, request: Request):
    d = await _body(request)
    con = get_con()
    _require_group_admin(con, request, gid)
    db.remove_member(con, gid, d.get("player_id"))
    con.close()
    return {"ok": True}


@app.post("/api/group/{gid}/delete")
async def api_group_delete(gid: str, request: Request):
    con = get_con()
    _require_group_admin(con, request, gid)
    db.delete_group(con, gid)     # matches kept (group_id -> NULL, former_group_name)
    con.close()
    return {"ok": True}


@app.post("/api/group/{gid}/leave")
async def api_group_leave(gid: str, request: Request):
    """A member leaves the group. The ADMIN cannot simply leave (it would orphan the group) —
    they must hand admin over or delete it; the client shows which. Matches are untouched."""
    con = get_con()
    u, p = require_player(con, request)
    g = db.group_by_id(con, gid)
    if not g:
        con.close()
        raise HTTPException(404, "group not found")
    if g["admin_id"] == p["id"]:
        con.close()
        return JSONResponse({"error": "You're the admin — hand admin over or delete the group to leave."}, 400)
    db.remove_member(con, gid, p["id"])
    con.close()
    return {"ok": True}


@app.get("/api/group/{gid}/requests")
def api_group_requests(gid: str, request: Request):
    con = get_con()
    _require_group_admin(con, request, gid)
    reqs = [_pblock(x) for x in db.join_requests_of(con, gid)]
    con.close()
    return {"requests": reqs}


@app.post("/api/group/{gid}/approve")
async def api_group_approve(gid: str, request: Request):
    d = await _body(request)
    con = get_con()
    _require_group_admin(con, request, gid)
    db.add_member(con, gid, d.get("player_id"))
    db.clear_join_request(con, gid, d.get("player_id"))
    con.close()
    return {"ok": True}


@app.post("/api/group/{gid}/decline")
async def api_group_decline(gid: str, request: Request):
    d = await _body(request)
    con = get_con()
    _require_group_admin(con, request, gid)
    db.clear_join_request(con, gid, d.get("player_id"))
    con.close()
    return {"ok": True}


# --- admin god-mode -------------------------------------------------------
def require_admin(request: Request):
    key = request.headers.get("x-admin-key") or request.query_params.get("key") or ""
    if not key or key != ADMIN_KEY:
        raise HTTPException(404, "Not Found")


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse(request, "admin.html", {})


@app.get("/admin/api/overview")
def admin_overview(request: Request):
    require_admin(request)
    con = get_con()
    groups = con.execute("SELECT COUNT(*) c FROM groups").fetchone()["c"]
    players = con.execute("SELECT COUNT(*) c FROM players").fetchone()["c"]
    matches = con.execute("SELECT COUNT(*) c FROM matches WHERE status<>'deleted'").fetchone()["c"]
    live = con.execute("SELECT COUNT(*) c FROM matches WHERE status='live'").fetchone()["c"]
    con.close()
    return {"groups": groups, "players": players, "matches": matches, "live": live}


@app.post("/admin/api/match/{mid}/delete")
async def admin_delete_match(mid: str, request: Request):
    require_admin(request)
    con = get_con()
    logic.delete_match(con, mid)
    con.close()
    return {"ok": True}
