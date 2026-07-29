/* Node tests for the client-side UX batch: the Create Game tab's create-vs-manage state (T2)
   and the Triple-Threat change-order Cancel (T8). Runs static/log.js in a vm sandbox with
   stubbed browser globals — same approach as test_boot.cjs.
   Run: node test_ux.cjs */
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const path = require("path");

function elStub(id) {
  return {
    id, innerHTML: "", textContent: "", style: {}, disabled: false,
    classList: { add() { }, remove() { }, toggle() { }, contains() { return false; } },
    appendChild() { }, querySelector() { return null; }, querySelectorAll() { return []; },
    addEventListener() { },
  };
}

// `let EDIT` in log.js is a LEXICAL binding, not a property of the sandbox object, so it has to
// be read and written by running code inside the context rather than touching sb.EDIT.
function setEdit(sb, obj) { sb.__e = obj; vm.runInContext("EDIT = __e;", sb); }
function getEdit(sb) { return vm.runInContext("EDIT", sb); }
// Objects built inside the vm have that realm's prototype, so deepStrictEqual would fail on
// identical data. Re-home them in this realm before comparing.
function plain(o) { return JSON.parse(JSON.stringify(o)); }

function makeSandbox() {
  const els = {};
  const doc = {
    getElementById(id) { return (els[id] = els[id] || elStub(id)); },
    querySelector() { return null },
    querySelectorAll() { return [] },
    createElement() { return elStub("new") },
    body: { appendChild() { } },
    addEventListener() { },
  };
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval,
    Promise, JSON, Math, Date, Object, Array, String, Number,
    document: doc, window: {}, location: { pathname: "/" },
    // helpers log.js borrows from app.js
    esc: (s) => String(s == null ? "" : s),
    el: (h) => elStub("el"),
    api: () => Promise.resolve({}),
    G: (p) => "/api" + p,
    ok: (d) => !!d,
    resilient: (f) => f(),
    poll: () => 0,
    pBlock: (p) => String((p && p.name) || ""),
    toast: () => { },
    openFullSection: () => elStub("fullSecBody"),
    closeFullSection: () => { },
    _els: els,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "static", "log.js"), "utf8"), sandbox);
  return sandbox;
}

// ---- T2: the tab shows the creation form OR the live match, never both ----
{
  const sb = makeSandbox();

  setEdit(sb, null);
  sb.applyLogMode();
  assert.strictEqual(sb._els.createWrap.style.display, "", "no live match -> creation form visible");
  assert.strictEqual(sb._els.liveWrap.style.display, "none", "no live match -> no management view");

  setEdit(sb, { mid: "m1", kind: "singles" });
  sb.applyLogMode();
  assert.strictEqual(sb._els.createWrap.style.display, "none",
    "T2: once a match exists the creation form must disappear");
  assert.strictEqual(sb._els.liveWrap.style.display, "", "T2: its management view takes the tab");

  // ...and when that match ends, the form comes back on its own.
  setEdit(sb, null);
  sb.applyLogMode();
  assert.strictEqual(sb._els.createWrap.style.display, "", "match over -> creation form returns");
  assert.strictEqual(sb._els.liveWrap.style.display, "none");
  console.log("OK T2 create-vs-manage state");
}

// ---- T8: Cancel restores the prior order EXACTLY ----
{
  const sb = makeSandbox();
  let rendered = 0, confirmed = 0;
  sb.renderTTEditor = () => { rendered++; };
  sb.renderRotationConfirm = (host, conf) => { confirmed++; };

  const original = { server: "p1", receiver: "p2", sitter: "p3" };
  setEdit(sb, {
    mid: "m1", kind: "tt", rot: ["p1", "p2", "p3"],
    names: { p1: "Ann", p2: "Bob", p3: "Cat" },
    cur: { server: original.server, receiver: original.receiver, sitter: original.sitter },
    rotKnown: true, _pending: null,
  });

  sb.ttPickRotation();
  // the user starts changing it, then thinks better of it
  sb.ttPickSet("server", "p3", { parentElement: { querySelectorAll: () => [] }, classList: { add() { }, remove() { } } });
  getEdit(sb).cur = { server: "p3", receiver: "p1", sitter: "p2" };   // a half-applied change
  getEdit(sb).rotKnown = false;

  sb.ttCancelPick();
  assert.deepStrictEqual(plain(getEdit(sb).cur), original, "T8: Cancel must restore the exact prior order");
  assert.strictEqual(getEdit(sb).rotKnown, true, "T8: and the prior confirmed-ness");
  assert.strictEqual(getEdit(sb)._pick, null, "T8: the abandoned pick is cleared");
  assert.strictEqual(rendered, 1, "T8: returns to the ordinary editor");
  assert.strictEqual(confirmed, 0);
  console.log("OK T8 cancel restores order");
}

// ---- T8: cancelling from the "is this the standard rotation?" prompt goes back to it ----
{
  const sb = makeSandbox();
  let rendered = 0, confirmed = 0;
  sb.renderTTEditor = () => { rendered++; };
  sb.renderRotationConfirm = () => { confirmed++; };

  const pending = { winnerId: "p1", std: { server: "p2", receiver: "p3", sitter: "p1" }, prompt: "?" };
  setEdit(sb, {
    mid: "m1", kind: "tt", rot: ["p1", "p2", "p3"], names: { p1: "A", p2: "B", p3: "C" },
    cur: { server: "p1", receiver: "p2", sitter: "p3" }, rotKnown: true, _pending: pending,
  });
  sb.ttPickRotation();
  sb.ttCancelPick();
  assert.strictEqual(confirmed, 1, "T8: cancelling mid-prompt returns to the prompt, not the editor");
  assert.strictEqual(rendered, 0);
  assert.deepStrictEqual(plain(getEdit(sb)._pending), pending, "T8: the pending game is not lost");
  console.log("OK T8 cancel returns to the rotation prompt");
}

console.log("OK ux (node)");
