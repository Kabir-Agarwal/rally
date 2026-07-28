"use strict";
/* Rally client auth. Token in localStorage; Bearer sent on writes. Sign-in screen is inline
   (no popups): "Continue with Google" / "Player ID + password".
   - Real Supabase mode (SUPABASE_URL + SUPABASE_ANON_KEY set): Google uses the real Supabase
     OAuth redirect (opens the Google account chooser); the server verifies the returned token.
   - No keys: falls back silently to a local mock so the app keeps working. */
window.Auth = (function () {
  var TOK = "rally_token", EM = "rally_email", RT = "rally_refresh", LR = "rally_oauth_return";

  function safeGet(store, k) { try { return store.getItem(k); } catch (e) { return null; } }
  function safeSet(store, k, v) { try { store.setItem(k, v); } catch (e) { } }
  function safeDel(store, k) { try { store.removeItem(k); } catch (e) { } }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]); }); }

  function token() { return safeGet(localStorage, TOK) || ""; }
  function email() { return safeGet(localStorage, EM) || ""; }
  function refreshToken() { return safeGet(localStorage, RT) || ""; }
  function signedIn() { return !!token(); }
  function headers() { return signedIn() ? { "Authorization": "Bearer " + token() } : {}; }
  function set(t, e, rt) { safeSet(localStorage, TOK, t); if (e) safeSet(localStorage, EM, e); if (rt) safeSet(localStorage, RT, rt); }
  function signOut() { safeDel(localStorage, TOK); safeDel(localStorage, EM); safeDel(localStorage, RT); }

  // --- sign-in outcome: never swallowed. Recorded here + persisted across the reload. -----
  var _lastReturn = null;
  function recordReturn(obj) { _lastReturn = obj; safeSet(sessionStorage, LR, JSON.stringify(obj)); }
  function lastReturn() {
    if (_lastReturn) return _lastReturn;
    var s = safeGet(sessionStorage, LR);
    if (s) { try { _lastReturn = JSON.parse(s); } catch (e) { } }
    return _lastReturn;
  }
  function clearLastReturn() { _lastReturn = null; safeDel(sessionStorage, LR); }

  // On return from a Supabase OAuth redirect the outcome is in the hash OR the query. Inspect
  // BOTH; record whatever came back (token, error, PKCE code, or nothing) — never swallow it.
  (function captureOAuthReturn() {
    var hash = (window.location.hash || "").replace(/^#/, "");
    var query = (window.location.search || "").replace(/^\?/, "");
    var hp = new URLSearchParams(hash), qp = new URLSearchParams(query);
    var g = function (k) { return hp.get(k) || qp.get(k); };
    var token = g("access_token"), err = g("error") || g("error_code"),
      errDesc = g("error_description"), code = g("code");
    var hashHasParams = hash.length > 0 && hash.indexOf("=") >= 0;
    function strip() { try { history.replaceState(null, "", window.location.pathname); } catch (e) { } }

    if (token) {
      set(token, "", g("refresh_token"));        // keep the refresh token for renewal (Task 3)
      recordReturn({ ok: true });
      strip();
      refreshEmail();
    } else if (err || errDesc) {
      recordReturn({ ok: false, error: err || "error", description: errDesc || "" });
      strip();
    } else if (code) {                           // Supabase PKCE code flow — we only handle implicit
      recordReturn({ ok: false, error: "code_flow", description: "Supabase returned a code, not a token" });
      strip();
    } else if (hashHasParams) {                  // came back from a redirect with neither token nor error
      recordReturn({ ok: false, error: "empty", description: "came back from Google with no token and no error" });
      strip();
    }
    // no hash/error/code at all => ordinary page load => record nothing
  })();

  var _cfg = null;
  // Fetch the server auth config. NEVER falls back to "mock" (that was a fail-open into a dead end:
  // a stall showed a guest button the server refuses). Retries with backoff, 10s per attempt; only a
  // real server answer is cached. On total failure returns {mode:"error"} — NOT cached, NOT mock.
  async function config() {
    if (_cfg) return _cfg;
    var backoff = [500, 1500];                 // between the 3 attempts (>= 2 retries)
    for (var attempt = 0; attempt < 3; attempt++) {
      var to = new Promise(function (res) { setTimeout(function () { res(null); }, 10000); });  // 10s
      try {
        var r = await Promise.race([fetch("/api/auth/config").then(function (x) { return x.json(); }), to]);
        if (r && r.mode) { _cfg = r; return _cfg; }   // cache ONLY a genuine answer
      } catch (e) { /* retry */ }
      if (attempt < 2) await new Promise(function (res) { setTimeout(res, backoff[attempt]); });
    }
    return { mode: "error" };                   // unreachable -> explicit error, not a usable fallback
  }
  function resetConfig() { _cfg = null; }        // used by the Retry button; don't poison the page load
  async function refreshEmail() {
    try {
      var j = await (await fetch("/api/auth/me", { headers: headers() })).json();
      if (j && j.email) safeSet(localStorage, EM, j.email);
      return j && j.email;
    } catch (e) { return null; }
  }
  // Renew an expired session with the stored refresh token (Supabase access tokens last ~1h).
  // Success -> store the new tokens and return true. Failure/no-token -> clear tokens, return false.
  async function refreshSession() {
    var rt = refreshToken();
    if (!rt) return false;
    var cfg = await config();
    if (!cfg || cfg.mode !== "supabase" || !cfg.supabase_url) return false;
    try {
      var r = await fetch(cfg.supabase_url + "/auth/v1/token?grant_type=refresh_token", {
        method: "POST",
        headers: { "Content-Type": "application/json", "apikey": cfg.anon_key || "" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!r.ok) { signOut(); return false; }
      var j = await r.json();
      if (j && j.access_token) { set(j.access_token, "", j.refresh_token || rt); return true; }
      signOut(); return false;
    } catch (e) { signOut(); return false; }
  }

  async function _post(url, body) {
    var r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw (j.error || ("error " + r.status));
    return j;
  }
  // Google: real Supabase OAuth redirect when configured, else local mock.
  async function google(em) {
    var cfg = await config();
    if (cfg.mode === "supabase" && cfg.supabase_url) {
      var redirect = window.location.origin + window.location.pathname;
      window.location.href = cfg.supabase_url + "/auth/v1/authorize?provider=google&redirect_to=" + encodeURIComponent(redirect);
      return new Promise(function () { });    // navigating away
    }
    var r = await _post("/api/auth/google", { email: em }); set(r.token, r.email); return r;
  }
  // Player ID + password. The server returns a session token our own middleware accepts; it
  // never returns the player's email (the leaderboard prints player IDs publicly, so a
  // code -> email lookup would turn it into an email directory).
  async function playerSignin(pid, pw) {
    var r = await _post("/api/auth/player-id", { player_id: pid, password: pw });
    set(r.token || r.access_token, "", r.refresh_token);
    return r;
  }

  // Fallback (mock) mode: one "Continue" that is UNIQUE PER DEVICE. A random device id is
  // generated once and reused, so this phone always returns as the same account.
  function deviceId() {
    var d = localStorage.getItem("rally_device");
    if (!d) {
      d = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
        : ("d-" + Math.random().toString(36).slice(2) + Date.now().toString(36));
      localStorage.setItem("rally_device", d);
    }
    return d;
  }
  async function guest() { var r = await _post("/api/auth/guest", { device_id: deviceId() }); set(r.token, ""); return r; }

  var SHELL = function (inner) {
    return '<div class="card" style="margin-top:24px">' +
      '<div style="font-weight:800;font-size:18px;text-align:center">🎾 Rally</div>' +
      '<div class="muted" style="text-align:center;margin:4px 0 14px">tennis scorer</div>' +
      inner + '<div class="err" id="auErr"></div></div>';
  };

  // A small muted line showing why a previous sign-in attempt failed (never swallowed).
  function failLine() {
    var lr = lastReturn();
    if (!lr || lr.ok !== false) return "";
    var msg = lr.message || ("Sign-in failed: " + (lr.error || "") + (lr.description ? " — " + lr.description : ""));
    clearLastReturn();                                   // show once, don't persist forever
    return '<div class="muted" style="text-align:center;margin:0 0 10px;color:#c0392b">' + esc(msg.slice(0, 200)) + '</div>';
  }

  function _retryCard(host, onDone, msg) {
    host.innerHTML = SHELL(
      '<div class="muted" style="text-align:center;color:#c0392b;margin-bottom:10px">' + esc(msg) + '</div>' +
      '<button class="btn" id="auRetry">Retry</button>');
    host.querySelector("#auRetry").onclick = function () { resetConfig(); renderSignIn(host, onDone); };
  }

  async function renderSignIn(host, onDone) {
    // config() retries for up to ~32s. Say so honestly while it works instead of showing a bare
    // "…" that reads as a hang — and never show an error until the retries are actually spent.
    host.innerHTML = SHELL('<div class="muted" style="text-align:center" id="auWait">Connecting…</div>');
    var slow = setTimeout(function () {
      var w = host.querySelector("#auWait");
      if (w) w.textContent = "Connecting… slow connection, still trying";
    }, 4000);
    var fl = failLine();
    var cfg = await config();
    clearTimeout(slow);
    if (cfg.mode === "error") {                 // couldn't reach the server -> retry, never a dead button
      _retryCard(host, onDone, "Couldn't reach the server — retry");
      return;
    }
    if (cfg.mode !== "supabase") {
      // Guest "Continue" is rendered ONLY when the server explicitly allows it (cfg.guest). Never
      // as a fallback, and never when guest sign-in is disabled server-side.
      if (!cfg.guest) { _retryCard(host, onDone, "Sign-in isn't available right now — retry"); return; }
      host.innerHTML = SHELL(fl + '<button class="btn" id="auGo">Continue</button>');
      var err = host.querySelector("#auErr");
      host.querySelector("#auGo").onclick = async function () {
        err.textContent = "";
        try { await guest(); onDone(); } catch (e) { err.textContent = e; }
      };
      return;
    }
    // REAL: exactly two paths. Google is the ONLY way to create an account; player ID + password
    // is an alternate sign-in for players who already exist and have set one. Email sign-in was
    // removed — Supabase mails a link rather than a code unless its templates carry {{ .Token }},
    // and those cannot be edited without custom SMTP.
    host.innerHTML = SHELL(fl +
      '<button class="btn" id="auGoogle">Continue with Google</button>' +
      '<div class="muted" style="text-align:center;margin:12px 0 6px">or</div>' +
      '<button class="btn ghost" id="auPwToggle">Player ID + password</button>' +
      '<div id="auPwBox" style="display:none;margin-top:8px">' +
      '<input id="auPid" placeholder="Player ID (e.g. 44YZC)" autocapitalize="characters" autocomplete="username" maxlength="8">' +
      '<input id="auPw" type="password" placeholder="Password" autocomplete="current-password" style="margin-top:8px">' +
      '<button class="btn" style="margin-top:8px" id="auPwGo">Sign in</button></div>' +
      '<div class="muted" style="text-align:center;margin-top:14px">New here? Continue with Google.</div>');
    var err = host.querySelector("#auErr");
    var showErr = function (e) { err.textContent = e; };
    host.querySelector("#auGoogle").onclick = async function () {
      showErr(""); try { await google(); onDone(); } catch (e) { showErr(e); }
    };
    var pwBox = host.querySelector("#auPwBox");
    host.querySelector("#auPwToggle").onclick = function () {
      showErr("");
      pwBox.style.display = pwBox.style.display === "none" ? "block" : "none";
      if (pwBox.style.display === "block") host.querySelector("#auPid").focus();
    };
    host.querySelector("#auPwGo").onclick = async function () {
      showErr("");
      var pid = host.querySelector("#auPid").value.trim();
      var pw = host.querySelector("#auPw").value;
      if (!pid || !pw) return showErr("player ID and password required");
      try { await playerSignin(pid, pw); onDone(); } catch (e) { showErr(e); }
    };
    host.querySelector("#auPw").addEventListener("keydown", function (e) {
      if (e.key === "Enter") host.querySelector("#auPwGo").click();
    });
  }

  return {
    token: token, email: email, signedIn: signedIn, headers: headers, signOut: signOut,
    refreshToken: refreshToken, refreshSession: refreshSession,
    google: google, guest: guest, playerSignin: playerSignin,
    config: config, resetConfig: resetConfig, refreshEmail: refreshEmail, renderSignIn: renderSignIn,
    lastReturn: lastReturn, recordReturn: recordReturn, clearLastReturn: clearLastReturn
  };
})();
