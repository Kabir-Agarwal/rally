/* Node test for the fail-open boot logic in static/app.js. Runs app.js in a vm sandbox with
   stubbed browser globals, then exercises staleTokenGuard / raceTimeout / failOpen.
   Run: node test_boot.cjs */
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const path = require("path");

function makeSandbox() {
  const store = {};
  const authState = { signedOut: false, refreshResult: false, recorded: null, lastReturn: null };
  const auth = {
    _token: null,
    signedIn() { return !!store.rally_token; },
    signOut() { delete store.rally_token; delete store.rally_refresh; authState.signedOut = true; },
    headers() { return store.rally_token ? { Authorization: "Bearer " + store.rally_token } : {}; },
    email() { return store.rally_email || ""; },
    refreshEmail() { return Promise.resolve(null); },
    renderSignIn(host, cb) { host.__signIn = true; },
    config() { return Promise.resolve({ mode: "mock" }); },
    refreshToken() { return store.rally_refresh || ""; },
    async refreshSession() {                       // configurable per test via authState.refreshResult
      if (authState.refreshResult) { store.rally_token = "renewed-token"; return true; }
      delete store.rally_token; delete store.rally_refresh; authState.signedOut = true; return false;
    },
    lastReturn() { return authState.lastReturn; },
    recordReturn(o) { authState.recorded = o; authState.lastReturn = o; },
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
    // RALLY_NO_AUTOBOOT: app.js otherwise kicks boot off via setTimeout(...,0), which would race
    // every test below (and consume the run-once guard before a test could call startBoot itself).
    window: { PAGE: "landing", Auth: auth, SyncQueue: null, addEventListener() { }, RALLY_NO_AUTOBOOT: true },
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

// Run app.js in a sandbox. `fast` shrinks the network/watchdog budget so retry paths are quick to
// test; the REAL budget shipped to phones is asserted separately (test 11).
function load(sb, fast) {
  vm.createContext(sb); vm.runInContext(code, sb);
  if (fast !== false) {
    Object.assign(sb.window.NET, { tries: 3, ms: 60, backoff: [5, 5] });
    Object.assign(sb.window.BOOT, { stallMs: 200, maxMs: 600, slowNoteMs: 30, tickMs: 20 });
  }
  return sb;
}

const code = fs.readFileSync(path.join(__dirname, "static", "app.js"), "utf8");

(async () => {
  // 1) staleTokenGuard clears the token when the server says signed_in:false
  let sb = makeSandbox();
  sb._store.rally_token = "stale-token";
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: false }) });
  load(sb);
  await sb.staleTokenGuard();
  assert.strictEqual(sb._authState.signedOut, true, "signed_in:false -> signOut()");
  assert.ok(!("rally_token" in sb._store), "stale token cleared");

  // 2) a VALID session is NOT signed out
  sb = makeSandbox();
  sb._store.rally_token = "good-token";
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: true, email: "x@y" }) });
  load(sb);
  await sb.staleTokenGuard();
  assert.strictEqual(sb._authState.signedOut, false, "valid session kept");
  assert.strictEqual(sb._store.rally_token, "good-token");

  // 3) a STALLED /api/auth/me is RETRIED, then fails open: no hang, no sign-out, token kept
  sb = makeSandbox();
  sb._store.rally_token = "maybe-good";
  let stalls = 0;
  sb.fetch = () => { stalls++; return new Promise(() => { }); };   // never resolves
  load(sb);
  await sb.staleTokenGuard();                       // resolves via the retry budget, not a hang
  assert.strictEqual(stalls, sb.window.NET.tries, "a stalled /auth/me is retried, not failed once");
  assert.strictEqual(sb._authState.signedOut, false, "transient stall does not sign out");
  assert.strictEqual(sb._store.rally_token, "maybe-good", "stall must not nuke a maybe-good token");

  // 4) raceTimeout resolves to the fallback quickly when the promise stalls
  sb = makeSandbox(); load(sb);
  const r = await sb.raceTimeout(new Promise(() => { }), 50, "FALLBACK");
  assert.strictEqual(r, "FALLBACK", "raceTimeout returns fallback on timeout");

  // 5) failOpen when signed OUT renders the sign-in gate (global model: `/` serves the SPA, no
  //    landing page). showSignInGate is stubbed to record that it ran.
  sb = makeSandbox(); load(sb);
  sb.showSignInGate = () => { sb._host.__signIn = true; };   // override the DOM-heavy real one
  sb.failOpen();
  assert.strictEqual(sb._host.__signIn, true, "failOpen (signed out) -> sign-in gate rendered");

  // 6) Task 4: failOpen writes an error card (not blank) when auth.js is missing
  sb = makeSandbox(); sb.window.PAGE = "landing"; sb.window.Auth = undefined; sb.Auth = undefined;
  load(sb);
  sb.failOpen();
  assert.ok(/Rally couldn't start/.test(sb._host.innerHTML), "no-auth -> 'Rally couldn't start' card");
  assert.ok(/Reload/.test(sb._host.innerHTML), "error card has a reload button");

  // 7) Task 3: rejected token WITH a refresh token that SUCCEEDS -> session kept (not signed out)
  sb = makeSandbox(); sb._store.rally_token = "expired"; sb._store.rally_refresh = "rt";
  sb._authState.refreshResult = true;
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: false }) });
  load(sb);
  // first /me says false; refreshSession succeeds; but our stub /me always says false, so re-check
  // still false -> to prove "kept on success" we make /me flip to true after refresh:
  let calls = 0;
  sb.fetch = () => { calls++; return Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: calls > 1 }) }); };
  await sb.staleTokenGuard();
  assert.strictEqual(sb._authState.signedOut, false, "refresh succeeded -> session kept");

  // 8) Task 3: rejected token WITH a refresh token that FAILS -> clean sign-out, no hang
  sb = makeSandbox(); sb._store.rally_token = "expired"; sb._store.rally_refresh = "rt";
  sb._authState.refreshResult = false;
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: false }) });
  load(sb);
  const t1 = Date.now();
  await sb.staleTokenGuard();
  assert.ok(Date.now() - t1 < 6000, "refresh-fail path did not hang");
  assert.strictEqual(sb._authState.signedOut, true, "refresh failed -> clean sign-out");

  // 9) Task 3: NO refresh token -> behaves exactly as today (sign out on signed_in:false)
  sb = makeSandbox(); sb._store.rally_token = "expired";      // no rally_refresh
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: false }) });
  load(sb);
  await sb.staleTokenGuard();
  assert.strictEqual(sb._authState.signedOut, true, "no refresh token -> plain sign-out (as today)");

  // 10) Task 2: fresh OAuth token rejected by server -> a reason is recorded
  sb = makeSandbox(); sb._store.rally_token = "fresh"; sb._authState.lastReturn = { ok: true };
  sb.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: false }) });
  load(sb);
  await sb.staleTokenGuard();
  assert.ok(sb._authState.recorded && /server rejected/i.test(sb._authState.recorded.message),
    "fresh-token rejection surfaces a message");
  assert.strictEqual(sb._authState.signedOut, true);

  // ===== SLOW IS NOT BROKEN (2026-07-28) ==========================================
  // The bug: first load on a phone always showed "Rally couldn't start"; a reload always worked.
  // Cause: a blind `setTimeout(failOpen, 4500)` backstop plus one-shot 4-6s deadlines, versus a
  // ~1.5s serverless cold start + mobile RTT. These tests pin "retry before declaring failure".

  // 11) the SHIPPED budget (not the shrunken test one) must survive a cold start + mobile latency
  sb = makeSandbox(); load(sb, false);
  assert.ok(sb.window.NET.ms >= 10000, `per-attempt deadline too tight: ${sb.window.NET.ms}ms`);
  assert.ok(sb.window.NET.tries >= 3, `too few attempts: ${sb.window.NET.tries}`);
  assert.ok(sb.window.NET.ms * sb.window.NET.tries >= 30000, "total network budget under 30s");
  assert.ok(sb.window.BOOT.stallMs >= 20000, `watchdog gives up too early: ${sb.window.BOOT.stallMs}ms`);
  assert.ok(sb.window.BOOT.slowNoteMs < sb.window.BOOT.stallMs, "slow note must precede giving up");
  assert.ok(sb.window.BOOT.tickMs <= 2000, "watchdog must actually look at progress regularly");

  // 12) resilient() RECOVERS a transient failure — the whole point. 2 stalls then a good answer.
  sb = makeSandbox(); load(sb);
  let n = 0;
  const got = await sb.resilient(() => {
    n++;
    return n < 3 ? new Promise(() => { }) : Promise.resolve({ hello: "world" });
  });
  assert.strictEqual(n, 3, "should have taken 3 attempts");
  assert.deepStrictEqual(got, { hello: "world" }, "a slow start must still succeed");
  assert.ok(sb.ok(got), "ok() true for a real value");

  // 13) resilient() issues a NEW request per attempt (retrying one stalled promise is useless)
  sb = makeSandbox(); load(sb);
  let made = 0;
  const dead = await sb.resilient(() => { made++; return new Promise(() => { }); });
  assert.strictEqual(made, 3, "each attempt must call make() again");
  assert.strictEqual(sb.ok(dead), false, "exhausted -> FAILED sentinel");

  // 14) a slow-but-eventually-good /api/me must NOT be reported as signed-out. This was the
  //     sign-in mock-fallback bug's twin: ensureIdentity() fabricated {signed_in:false} after 4s.
  sb = makeSandbox(); sb._store.rally_token = "good"; load(sb);
  let meCalls = 0;
  sb.fetch = (url) => {
    meCalls++;
    if (meCalls < 3) return new Promise(() => { });          // two stalls
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ signed_in: true, player_id: "p1", player_name: "Ace" }) });
  };
  await sb.ensureIdentity();
  assert.strictEqual(sb.currentMe().signed_in, true, "slow /api/me must not read as signed out");
  assert.strictEqual(sb.currentMe().player_id, "p1", "identity resolved after retries");

  // 15) when /api/me is truly unreachable, ensureIdentity must NOT invent signed_in:false and must
  //     NOT push the 'Set up your player' gate at a user who may well have a player already.
  sb = makeSandbox(); sb._store.rally_token = "good"; load(sb);
  sb.fetch = () => new Promise(() => { });
  let nameGate = 0;
  sb.chooseName = () => { nameGate++; return Promise.resolve(true); };
  const before = JSON.stringify(sb.currentMe());
  await sb.ensureIdentity();
  assert.strictEqual(nameGate, 0, "unreachable server must not trigger the name gate");
  assert.strictEqual(JSON.stringify(sb.currentMe()), before, "ME must be left untouched, not fabricated");

  // 16) the watchdog is PROGRESS-aware: while boot keeps reaching milestones it must not fire,
  //     even long past the old 4.5s deadline; once progress stops it does fire.
  sb = makeSandbox(); sb._store.rally_token = "good"; load(sb);
  let failed = 0;
  sb.failOpen = () => { failed++; };
  sb.boot = () => new Promise(() => { });        // boot that never finishes, but reports progress
  sb.startBoot();
  const beat = setInterval(() => sb.bootStep("tick"), 40);   // steady progress, < stallMs apart
  await new Promise(res => setTimeout(res, 500));            // 500ms >> old 4.5s-equivalent budget
  assert.strictEqual(failed, 0, "watchdog fired while boot was still making progress");
  clearInterval(beat);                                        // progress stops -> now it may fire
  await new Promise(res => setTimeout(res, 400));
  assert.ok(failed >= 1, "watchdog never fired even though boot went silent");

  // 16b) the "slow connection" note must NEVER overwrite #tabContent. That container holds the
  //      tab panels; writing innerHTML into it detached the rendered panel (PANELS kept the
  //      orphan, so renderTab wouldn't rebuild) and the app went blank on a slow connection.
  sb = makeSandbox();
  let appended = 0, tabWrites = 0;
  const appEl = { appendChild() { appended++; }, querySelector() { return null; } };
  const tabEl = { querySelector() { return null; }, style: {} };
  Object.defineProperty(tabEl, "innerHTML", { get() { return ""; }, set() { tabWrites++; } });
  sb.document.getElementById = (id) => (id === "tabContent" ? tabEl
    : id === "bootSlow" ? null : sb._host);
  sb.document.querySelector = (s) => (s === ".app" ? appEl : null);
  load(sb);
  sb.window.BOOT.slowNoteMs = 0;               // due immediately, without running a whole boot
  sb.bootSlowNote();
  assert.strictEqual(tabWrites, 0, "the slow note must not write into #tabContent (it holds the panels)");
  assert.strictEqual(appended, 1, "the slow note should be appended as its own node");

  // 17) a boot that THROWS is genuinely broken -> failOpen immediately (no waiting it out)
  sb = makeSandbox(); sb._store.rally_token = "good"; load(sb);
  let failed2 = 0;
  sb.failOpen = () => { failed2++; };
  sb.boot = () => Promise.reject(new Error("kaboom"));
  sb.startBoot();
  await new Promise(res => setTimeout(res, 50));
  assert.strictEqual(failed2, 1, "a thrown boot error must fail open at once");

  // 18) a boot that SUCCEEDS must stop the watchdog, so failOpen can never fire afterwards
  sb = makeSandbox(); sb._store.rally_token = "good"; load(sb);
  let failed3 = 0;
  sb.failOpen = () => { failed3++; };
  sb.boot = () => Promise.resolve(true);
  sb.startBoot();
  await new Promise(res => setTimeout(res, 900));   // well past stallMs and maxMs
  assert.strictEqual(failed3, 0, "watchdog fired after a successful boot");

  console.log("OK boot (node)");
})().catch(e => { console.error(e); process.exit(1); });
