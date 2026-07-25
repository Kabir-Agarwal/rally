/* Node test for the fail-open boot logic in static/app.js. Runs app.js in a vm sandbox with
   stubbed browser globals, then exercises staleTokenGuard / raceTimeout / failOpen.
   Run: node test_boot.cjs */
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const path = require("path");

function makeSandbox() {
  const store = {};
  const authState = { signedOut: false };
  const auth = {
    _token: null,
    signedIn() { return !!store.rally_token; },
    signOut() { delete store.rally_token; authState.signedOut = true; },
    headers() { return store.rally_token ? { Authorization: "Bearer " + store.rally_token } : {}; },
    email() { return store.rally_email || ""; },
    refreshEmail() { return Promise.resolve(null); },
    renderSignIn(host, cb) { host.__signIn = true; },
    config() { return Promise.resolve({ mode: "mock" }); },
  };
  const host = { __signIn: false, innerHTML: "" };
  const doc = {
    addEventListener() { },                       // boot listener never auto-fires in the test
    getElementById() { return host; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return { style: {}, classList: { add() {}, remove() {}, toggle() {} }, appendChild() {}, querySelector() { return null }, innerHTML: "" }; },
    body: { appendChild() {} },
  };
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, URLSearchParams, Math, Date, JSON, Array, Object, String,
    fetch: null, localStorage: {
      getItem: k => (k in store ? store[k] : null), setItem: (k, v) => store[k] = String(v),
      removeItem: k => delete store[k], clear: () => Object.keys(store).forEach(k => delete store[k]),
    },
    document: doc, history: { pushState() {}, replaceState() {}, back() {}, state: null },
    location: { pathname: "/", reload() {} },
    window: { PAGE: "landing", Auth: auth, SyncQueue: null, addEventListener() { } },
    Auth: auth,
    // stubs for functions app.js expects from log.js (loaded before app.js in the browser)
    initLive() { }, initRanks() { }, initLog() { }, initGroups() { }, initHistory() { },
    Engine: {}, addEventListener() { },
    _store: store, _authState: authState, _host: host,
  };
  sandbox.globalThis = sandbox;
  sandbox.window.location = sandbox.location;
  sandbox.window.history = sandbox.history;
  return sandbox;
}

const code = fs.readFileSync(path.join(__dirname, "static", "app.js"), "utf8");

(async () => {
  // 1) staleTokenGuard clears the token when the server says signed_in:false
  let sb = makeSandbox();
  sb._store.rally_token = "stale-token";
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: false }) });
  vm.createContext(sb); vm.runInContext(code, sb);
  await sb.staleTokenGuard();
  assert.strictEqual(sb._authState.signedOut, true, "signed_in:false -> signOut()");
  assert.ok(!("rally_token" in sb._store), "stale token cleared");

  // 2) a VALID session is NOT signed out
  sb = makeSandbox();
  sb._store.rally_token = "good-token";
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: true, email: "x@y" }) });
  vm.createContext(sb); vm.runInContext(code, sb);
  await sb.staleTokenGuard();
  assert.strictEqual(sb._authState.signedOut, false, "valid session kept");
  assert.strictEqual(sb._store.rally_token, "good-token");

  // 3) a STALLED /api/auth/me does not hang and does not nuke the token (fails open)
  sb = makeSandbox();
  sb._store.rally_token = "maybe-good";
  sb.fetch = () => new Promise(() => { });          // never resolves
  vm.createContext(sb); vm.runInContext(code, sb);
  const t0 = Date.now();
  await sb.staleTokenGuard();                         // must resolve via the 4s timeout, not hang
  assert.ok(Date.now() - t0 >= 3900, "guard waited for the bounded timeout");
  assert.strictEqual(sb._authState.signedOut, false, "transient stall does not sign out");

  // 4) raceTimeout resolves to the fallback quickly when the promise stalls
  sb = makeSandbox(); vm.createContext(sb); vm.runInContext(code, sb);
  const r = await sb.raceTimeout(new Promise(() => { }), 50, "FALLBACK");
  assert.strictEqual(r, "FALLBACK", "raceTimeout returns fallback on timeout");

  // 5) failOpen renders the sign-in view on the landing page
  sb = makeSandbox(); sb.window.PAGE = "landing"; vm.createContext(sb); vm.runInContext(code, sb);
  sb.failOpen();
  assert.strictEqual(sb._host.__signIn, true, "failOpen -> sign-in view rendered");

  console.log("OK boot (node)");
})().catch(e => { console.error(e); process.exit(1); });
