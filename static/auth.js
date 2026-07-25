"use strict";
/* Rally client auth. Token in localStorage; Bearer sent on writes. Sign-in screen is inline
   (no popups): "Continue with Google" / "Continue with email" (6-digit OTP).
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
  async function config() {
    if (_cfg) return _cfg;
    // bounded so the sign-in screen never hangs on "…" if /api/auth/config stalls
    var timeout = new Promise(function (res) { setTimeout(function () { res({ mode: "mock" }); }, 4000); });
    try {
      _cfg = await Promise.race([fetch("/api/auth/config").then(function (r) { return r.json(); }), timeout]);
    } catch (e) { _cfg = { mode: "mock" }; }
    if (!_cfg || !_cfg.mode) _cfg = { mode: "mock" };
    return _cfg;
  }
  async function refreshEmail() {
    try {
      var j = await (await fetch("/api/auth/me", { headers: headers() })).json();
      if (j && j.email) localStorage.setItem(EM, j.email);
      return j && j.email;
    } catch (e) { return null; }
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
  async function emailStart(em) { return _post("/api/auth/email/start", { email: em }); }
  async function emailVerify(em, code) { var r = await _post("/api/auth/email/verify", { email: em, code: code }); set(r.token, r.email); return r; }

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

  async function renderSignIn(host, onDone) {
    host.innerHTML = SHELL('<div class="muted" style="text-align:center">…</div>');
    var fl = failLine();
    var cfg = await config();
    if (cfg.mode !== "supabase") {
      // FALLBACK: a single Continue button. No Google, no email, no code — ever.
      host.innerHTML = SHELL(fl + '<button class="btn" id="auGo">Continue</button>');
      var err = host.querySelector("#auErr");
      host.querySelector("#auGo").onclick = async function () {
        err.textContent = "";
        try { await guest(); onDone(); } catch (e) { err.textContent = e; }
      };
      return;
    }
    // REAL: Google + email OTP. The OTP code is typed by the user and never shown on screen.
    host.innerHTML = SHELL(fl +
      '<button class="btn" id="auGoogle">Continue with Google</button>' +
      '<div class="muted" style="text-align:center;margin:12px 0 6px">or</div>' +
      '<div id="auEmailBox"><input id="auEmail" type="email" placeholder="you@email.com" autocomplete="email">' +
      '<button class="btn ghost" style="margin-top:8px" id="auSend">Continue with email</button></div>' +
      '<div id="auOtpBox" style="display:none"><div class="muted" id="auOtpNote" style="margin-bottom:6px"></div>' +
      '<input id="auCode" inputmode="numeric" maxlength="6" placeholder="6-digit code">' +
      '<button class="btn" style="margin-top:8px" id="auVerify">Verify</button></div>');
    var err = host.querySelector("#auErr");
    var showErr = function (e) { err.textContent = e; };
    host.querySelector("#auGoogle").onclick = async function () {
      showErr(""); try { await google(); onDone(); } catch (e) { showErr(e); }
    };
    host.querySelector("#auSend").onclick = async function () {
      showErr("");
      var em = host.querySelector("#auEmail").value.trim();
      if (!em) return showErr("enter your email");
      try {
        var r = await emailStart(em);
        if (r.error) return showErr(r.error);
        host.querySelector("#auEmailBox").style.display = "none";
        host.querySelector("#auOtpBox").style.display = "block";
        host.querySelector("#auOtpNote").textContent = "Code sent to " + em;   // never the code
        host.querySelector("#auVerify").onclick = async function () {
          showErr("");
          var code = host.querySelector("#auCode").value.trim();
          try { await emailVerify(em, code); onDone(); } catch (e) { showErr(e); }
        };
      } catch (e) { showErr(e); }
    };
  }

  return {
    token: token, email: email, signedIn: signedIn, headers: headers, signOut: signOut,
    google: google, guest: guest, emailStart: emailStart, emailVerify: emailVerify,
    config: config, refreshEmail: refreshEmail, renderSignIn: renderSignIn
  };
})();
