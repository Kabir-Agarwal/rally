"""Serving order (positional) + per-point reconstruction + serve/return & story stats.

Ratings NEVER use point data. This module produces:
  - serving order helpers (who serves each game)
  - point_logs -> match_sets (games) so per-point scoring feeds the game-based rating
  - display-only serve/return stats and match-story stats
"""
from __future__ import annotations
import db


# --- serving order (positional, no questions) -----------------------------
def singles_server(order, game_idx):
    """order = [p1, p2]; P1 serves game 0, alternate."""
    return order[game_idx % 2]


def doubles_server(order, game_idx):
    """order = [t1a, t2a, t1b, t2b] (serving order); 4-game cycle."""
    return order[game_idx % 4]


def tt_server(rotation, game_idx):
    return rotation[game_idx % 3]


def tt_pairing(rotation, game_idx):
    """Return (server, receiver, sitter) for a triple-threat game."""
    i = game_idx % 3
    pairs = [(rotation[0], rotation[1]), (rotation[1], rotation[2]), (rotation[2], rotation[0])]
    server, receiver = pairs[i]
    sitter = rotation[(i + 2) % 3]
    return server, receiver, sitter


# --- per-point reconstruction --------------------------------------------
def score_points(points):
    """points: list of winner_side (1|2) in order.

    Returns dict with completed `sets` [(g1,g2)], `cur_games` (g1,g2) for the in-progress
    set, current game `points` (raw counts), `is_tiebreak`, and `games` — a per-game log
    [(winner_side, gi_index)] for serve attribution.
    """
    sets = []
    g = [0, 0]
    pts = [0, 0]
    games = []          # winner_side per completed game, in order
    gi = 0
    for w in points:
        i = w - 1
        pts[i] += 1
        is_tb = (g[0] == 6 and g[1] == 6)
        need = 7 if is_tb else 4
        if pts[i] >= need and pts[i] - pts[1 - i] >= 2:
            g[i] += 1
            games.append((w, gi))
            gi += 1
            pts = [0, 0]
            if (g[i] >= 6 and g[i] - g[1 - i] >= 2) or g[i] == 7:
                sets.append((g[0], g[1]))
                g = [0, 0]
    return {
        "sets": sets,
        "cur_games": (g[0], g[1]),
        "points": (pts[0], pts[1]),
        "is_tiebreak": (g[0] == 6 and g[1] == 6),
        "games": games,
    }


POINT_LABELS = {0: "0", 1: "15", 2: "30", 3: "40"}


def point_display(pts, is_tiebreak):
    """Human label for the current game score (15/30/40/deuce/adv or raw tiebreak)."""
    a, b = pts
    if is_tiebreak:
        return f"{a}-{b}"
    if a >= 3 and b >= 3:
        if a == b:
            return "Deuce"
        return "Ad" if a > b else "Ad-out"
    return f"{POINT_LABELS.get(a, '40')}-{POINT_LABELS.get(b, '40')}"


def all_sets_for_storage(points):
    """Completed sets + current partial set (if any games) — for writing match_sets."""
    sc = score_points(points)
    out = list(sc["sets"])
    if sc["cur_games"] != (0, 0):
        out.append(sc["cur_games"])
    return out


# --- serve / return stats (display only) ---------------------------------
def serve_return_stats(con, group_id, player_id):
    """Aggregate hold%/break% and games served across a player's per-point + TT matches.

    Serve stats individual; doubles return stats team-level. TT games feed hold/break.
    # ponytail: hold/break only (games served vs held/broken). Break-points-saved and the
    # richer story stats live in match_story(); this stays the leaderboard/player summary.
    """
    served = held = ret_games = broke = 0
    live_matches = 0
    if group_id is None:                       # global player page: all of this player's matches
        ms = con.execute(
            "SELECT m.* FROM matches m JOIN match_players mp ON mp.match_id=m.id "
            "WHERE mp.player_id=? AND m.kind IN ('singles','doubles','tt')", (player_id,)
        ).fetchall()
    else:
        ms = con.execute(
            "SELECT * FROM matches WHERE group_id=? AND kind IN ('singles','doubles','tt')", (group_id,)
        ).fetchall()
    for m in ms:
        s1, s2, rot = db.sides(con, m["id"])
        mine = None
        if m["kind"] == "tt":
            if player_id not in rot:
                continue
            games = db.tt_games(con, m["id"])
            if not games:
                continue
            live_matches += 1
            for gno, gm in enumerate(games):
                srv = gm["server_player_id"]
                win = gm["winner_player_id"]
                rec = gm["receiver_player_id"] if "receiver_player_id" in gm.keys() else None
                if srv == player_id:
                    served += 1
                    if win == player_id:
                        held += 1
                elif rec == player_id:                 # confirmed receiver of this game
                    ret_games += 1
                    if win == player_id:
                        broke += 1
                elif rec is None and win == player_id and srv is not None and srv != player_id:
                    ret_games += 1                      # legacy: infer winner was the receiver
                    broke += 1
            continue
        # per-point singles/doubles
        if player_id in s1:
            mine = 1
        elif player_id in s2:
            mine = 2
        else:
            continue
        pts = con.execute(
            "SELECT winner_side FROM point_logs WHERE match_id=? ORDER BY seq", (m["id"],)
        ).fetchall()
        if not pts:
            continue
        live_matches += 1
        sc = score_points([p["winner_side"] for p in pts])
        order = _serve_order(s1, s2, m["kind"])
        for win_side, gi in sc["games"]:
            server = singles_server(order, gi) if m["kind"] == "singles" else doubles_server(order, gi)
            server_side = 1 if server in s1 else 2
            if server == player_id:  # individual serve
                served += 1
                if win_side == server_side:
                    held += 1
            elif server_side == mine:
                # partner served — not my serve, skip for serve stats
                pass
            else:
                # opponent served: return game (team-level)
                ret_games += 1
                if win_side == mine:
                    broke += 1
    return {
        "hold_pct": round(100 * held / served) if served else None,
        "break_pct": round(100 * broke / ret_games) if ret_games else None,
        "served": served, "held": held, "ret_games": ret_games, "broke": broke,
        "live_matches": live_matches,
    }


def _serve_order(s1, s2, kind):
    if kind == "singles":
        return [s1[0], s2[0]]
    # doubles serving order: T1a, T2a, T1b, T2b
    return [s1[0], s2[0], s1[1], s2[1]]


def match_story(con, mid):
    """Story strip for a per-point match: holds/breaks, biggest set comeback, deuce pts,
    longest streak, game points saved. Display only. Returns None for typed matches."""
    m = db.match_row(con, mid)
    if m["kind"] == "tt":
        return None
    pts = con.execute(
        "SELECT winner_side, server_player_id FROM point_logs WHERE match_id=? ORDER BY seq", (mid,)
    ).fetchall()
    if not pts:
        return None
    seq = [p["winner_side"] for p in pts]
    sc = score_points(seq)

    # longest point streak
    longest = cur = 0
    last = None
    for w in seq:
        cur = cur + 1 if w == last else 1
        last = w
        longest = max(longest, cur)

    # deuce points won (points played at 3-3+ within a game) — approx from raw game replay
    deuce_pts = _deuce_points(seq)

    # holds / breaks and game points saved
    s1, s2, _ = db.sides(con, mid)
    order = _serve_order(s1, s2, m["kind"])
    holds = breaks = saved = 0
    for gi, (win_side, gidx) in enumerate(sc["games"]):
        server = singles_server(order, gidx) if m["kind"] == "singles" else doubles_server(order, gidx)
        server_side = 1 if server in s1 else 2
        if win_side == server_side:
            holds += 1
        else:
            breaks += 1

    # biggest set comeback: max deficit overcome by the eventual set winner
    comeback = _biggest_comeback(sc["sets"])

    return {
        "holds": holds, "breaks": breaks, "longest_streak": longest,
        "deuce_points": deuce_pts, "comeback": comeback,
        "saved_game_points": _game_points_saved(seq),
    }


def _deuce_points(seq):
    """Count points played while a game was at 40-40 or beyond (both >=3)."""
    pts = [0, 0]
    g = [0, 0]
    count = 0
    for w in seq:
        i = w - 1
        if pts[0] >= 3 and pts[1] >= 3:
            count += 1  # this point was a deuce/ad point
        pts[i] += 1
        is_tb = (g[0] == 6 and g[1] == 6)
        need = 7 if is_tb else 4
        if pts[i] >= need and pts[i] - pts[1 - i] >= 2:
            g[i] += 1
            pts = [0, 0]
            if (g[i] >= 6 and g[i] - g[1 - i] >= 2) or g[i] == 7:
                g = [0, 0]
    return count


def _game_points_saved(seq):
    """Points where a player faced game/break point against them and did not lose that point."""
    pts = [0, 0]
    g = [0, 0]
    saved = 0
    for w in seq:
        is_tb = (g[0] == 6 and g[1] == 6)
        need = 7 if is_tb else 4
        # before playing: does either side hold a game point?
        for i in (0, 1):
            if pts[i] >= need - 1 and pts[i] - pts[1 - i] >= 1:
                # side i has a game point; if the OTHER side wins this point, it's saved
                if w - 1 != i:
                    saved += 1
        i = w - 1
        pts[i] += 1
        if pts[i] >= need and pts[i] - pts[1 - i] >= 2:
            g[i] += 1
            pts = [0, 0]
            if (g[i] >= 6 and g[i] - g[1 - i] >= 2) or g[i] == 7:
                g = [0, 0]
    return saved


def _biggest_comeback(sets):
    """Largest game deficit the eventual set winner trailed by, across sets (coarse)."""
    best = 0
    for a, b in sets:
        winner = 1 if a > b else 2
        loser_games = b if winner == 1 else a
        # winner trailed by at most loser_games (coarse upper bound of comeback size)
        if (a > b and b >= 4) or (b > a and a >= 4):
            best = max(best, loser_games)
    return best


if __name__ == "__main__":
    # serving order
    assert singles_server(["p1", "p2"], 0) == "p1" and singles_server(["p1", "p2"], 1) == "p2"
    order = ["a", "c", "b", "d"]  # doubles t1a,t2a,t1b,t2b
    assert [doubles_server(order, i) for i in range(4)] == ["a", "c", "b", "d"]
    srv, rec, sit = tt_pairing(["p1", "p2", "p3"], 0)
    assert (srv, rec, sit) == ("p1", "p2", "p3")
    srv, rec, sit = tt_pairing(["p1", "p2", "p3"], 1)
    assert (srv, rec, sit) == ("p2", "p3", "p1")

    # reconstruct: 4 straight points -> a game to side 1
    sc = score_points([1, 1, 1, 1])
    assert sc["cur_games"] == (1, 0), sc
    # a full 6-0 set
    sc = score_points([1, 1, 1, 1] * 6)
    assert sc["sets"] == [(6, 0)], sc
    # deuce display
    assert point_display((3, 3), False) == "Deuce"
    assert point_display((4, 3), False) == "Ad"
    # 7-6 tiebreak set: 6 games each then tiebreak to 7
    seq = ([1, 1, 1, 1, 2, 2, 2, 2] * 6) + [1, 1, 1, 1, 1, 1, 1]
    sc = score_points(seq)
    assert sc["sets"] and sc["sets"][0] == (7, 6), sc["sets"]
    print("OK scoring")
