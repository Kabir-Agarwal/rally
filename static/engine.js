/* Rally client-side scoring engine (Task 2a).
   Mirrors the server's scoring.py EXACTLY so the browser can score instantly from local
   state and the server recompute agrees byte-for-byte on replay. Pure functions + a tiny
   stateful wrapper. Works in the browser (window.Engine) and Node (module.exports). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Engine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var POINT_LABELS = { 0: "0", 1: "15", 2: "30", 3: "40" };

  // ---- pure: point sequence -> sets/games/points (mirror of scoring.score_points) ----
  function scorePoints(points) {
    var sets = [], g = [0, 0], pts = [0, 0], games = [];
    for (var k = 0; k < points.length; k++) {
      var i = points[k] - 1;
      pts[i] += 1;
      var isTb = (g[0] === 6 && g[1] === 6);
      var need = isTb ? 7 : 4;
      if (pts[i] >= need && pts[i] - pts[1 - i] >= 2) {
        g[i] += 1;
        games.push(points[k]);
        pts = [0, 0];
        if ((g[i] >= 6 && g[i] - g[1 - i] >= 2) || g[i] === 7) {
          sets.push([g[0], g[1]]);
          g = [0, 0];
        }
      }
    }
    return {
      sets: sets, curGames: [g[0], g[1]], points: [pts[0], pts[1]],
      isTiebreak: (g[0] === 6 && g[1] === 6), games: games
    };
  }

  function pointDisplay(pts, isTiebreak) {
    var a = pts[0], b = pts[1];
    if (isTiebreak) return a + "-" + b;
    if (a >= 3 && b >= 3) return a === b ? "Deuce" : (a > b ? "Ad" : "Ad-out");
    return (POINT_LABELS[a] || "40") + "-" + (POINT_LABELS[b] || "40");
  }

  // sets for storage = completed + current partial (if any games/points) — mirrors server
  function allSetsForStorage(points) {
    var sc = scorePoints(points);
    var out = sc.sets.slice();
    if (sc.curGames[0] !== 0 || sc.curGames[1] !== 0) out.push(sc.curGames);
    return out;
  }

  // ---- serving order (mirror of scoring.py) ----
  function singlesServer(order, gi) { return order[gi % 2]; }
  function doublesServer(order, gi) { return order[gi % 4]; }        // [t1a,t2a,t1b,t2b]
  function ttPairing(rotation, gi) {
    var i = gi % 3;
    var pairs = [[rotation[0], rotation[1]], [rotation[1], rotation[2]], [rotation[2], rotation[0]]];
    return { server: pairs[i][0], receiver: pairs[i][1], sitter: rotation[(i + 2) % 3] };
  }

  // ---- stateful per-point match (singles/doubles) ----
  function PointMatch(kind, order) {
    this.kind = kind;               // 'singles' | 'doubles'
    this.order = order;             // serving-order player ids
    this.points = [];               // winner_side per point (1|2)
  }
  PointMatch.prototype.addPoint = function (side) { this.points.push(side); return this.snapshot(); };
  PointMatch.prototype.undo = function () { this.points.pop(); return this.snapshot(); };
  PointMatch.prototype.snapshot = function () {
    var sc = scorePoints(this.points);
    var gi = sc.games.length;
    var server = this.order && this.order.length
      ? (this.kind === "singles" ? singlesServer(this.order, gi) : doublesServer(this.order, gi))
      : null;
    return {
      sets: sc.sets, curGames: sc.curGames,
      pointLabel: pointDisplay(sc.points, sc.isTiebreak),
      isTiebreak: sc.isTiebreak, server: server,
      storageSets: allSetsForStorage(this.points), points: this.points.slice()
    };
  };

  // ---- stateful triple-threat (game/rotation) ----
  function TTMatch(rotation) {
    this.rotation = rotation;       // [p1,p2,p3] serving/rotation order
    this.games = [];                // winner_player_id per game
  }
  TTMatch.prototype.addGame = function (winnerId) { this.games.push(winnerId); return this.snapshot(); };
  TTMatch.prototype.undo = function () { this.games.pop(); return this.snapshot(); };
  TTMatch.prototype.snapshot = function () {
    var tally = {};
    for (var r = 0; r < this.rotation.length; r++) tally[this.rotation[r]] = 0;
    for (var i = 0; i < this.games.length; i++)
      if (tally[this.games[i]] !== undefined) tally[this.games[i]] += 1;
    return {
      gameNo: this.games.length,
      pairing: this.rotation.length === 3 ? ttPairing(this.rotation, this.games.length) : null,
      tally: tally, games: this.games.slice()
    };
  };

  return {
    scorePoints: scorePoints, pointDisplay: pointDisplay, allSetsForStorage: allSetsForStorage,
    singlesServer: singlesServer, doublesServer: doublesServer, ttPairing: ttPairing,
    PointMatch: PointMatch, TTMatch: TTMatch
  };
});
