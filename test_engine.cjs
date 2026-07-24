/* Node unit test for the client scoring engine. Run: node test_engine.cjs */
const assert = require("assert");
const E = require("./static/engine.js");

// a game = 4 straight points
let m = new E.PointMatch("singles", ["a", "b"]);
let s;
for (let i = 0; i < 4; i++) s = m.addPoint(1);
assert.deepStrictEqual(s.curGames, [1, 0], "4 points -> 1 game");
// server rotated to b for game 2 (game index 1)
assert.strictEqual(s.server, "b", "server alternates after game 1");

// deuce / Ad labels
m = new E.PointMatch("singles", ["a", "b"]);
m.addPoint(1); m.addPoint(1); m.addPoint(1);      // 40-0
m.addPoint(2); m.addPoint(2); m.addPoint(2);      // 40-40
assert.strictEqual(m.snapshot().pointLabel, "Deuce");
assert.strictEqual(m.addPoint(1).pointLabel, "Ad");
assert.strictEqual(m.addPoint(2).pointLabel, "Deuce");

// undo reverses the last point
m = new E.PointMatch("singles", ["a", "b"]);
m.addPoint(1); let before = m.snapshot().pointLabel;
m.addPoint(1); m.undo();
assert.strictEqual(m.snapshot().pointLabel, before, "undo restores prior state");

// a full 6-0 set
m = new E.PointMatch("singles", ["a", "b"]);
for (let i = 0; i < 24; i++) m.addPoint(1);
assert.deepStrictEqual(m.snapshot().sets, [[6, 0]], "6-0 set");

// 7-6 tiebreak set
m = new E.PointMatch("singles", ["a", "b"]);
const seq = [];
for (let g = 0; g < 6; g++) { for (let p = 0; p < 4; p++) seq.push(1); for (let p = 0; p < 4; p++) seq.push(2); }
for (let p = 0; p < 7; p++) seq.push(1);           // tiebreak to 7-0
seq.forEach(x => m.addPoint(x));
assert.deepStrictEqual(m.snapshot().sets, [[7, 6]], "tiebreak set 7-6");

// TT rotation + tally
let t = new E.TTMatch(["p1", "p2", "p3"]);
let ts = t.snapshot();
assert.deepStrictEqual([ts.pairing.server, ts.pairing.receiver, ts.pairing.sitter], ["p1", "p2", "p3"]);
ts = t.addGame("p1");
assert.strictEqual(ts.tally["p1"], 1);
assert.deepStrictEqual([ts.pairing.server, ts.pairing.receiver, ts.pairing.sitter], ["p2", "p3", "p1"], "rotation advances");
t.undo();
assert.strictEqual(t.snapshot().gameNo, 0, "TT undo");

console.log("OK engine (node)");
