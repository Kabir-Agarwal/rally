"use strict";
/* Rally client auth. Token in localStorage; Bearer sent on writes. Sign-in screen is inline
   (no popups): "Continue with Google" / "Continue with email" (6-digit OTP).
   - Real Supabase mode (SUPABASE_URL + SUPABASE_ANON_KEY set): Google uses the real Supabase
     OAuth redirect (opens the Google account chooser); the server verifies the returned token.
   - No keys: falls back silently to a local mock so the app keeps working. */
window.Auth = (function () {
  var TOK = "rally_token", EM = "rally_email";

  function token() { return localStorage.getItem(TOK) || ""; }
  function email() { return localStorage.getItem(EM) || ""; }
  function signedIn() { return !!token(); }
  function headers() { return signedIn() ? { "Authorization": "Bearer " + token() } : {}; }
  function set(t, e) { localStorage.setItem(TOK, t); if (e) localStorage.setItem(EM, e); }
  function signOut() { localStorage.removeItem(TOK); localStorage.removeItem(EM); }

  // On return from a Supabase OAuth redirect the token arrives in the URL hash. Capture it.
  (function captureOAuthReturn() {
    var h = window.location.hash || "";
    if (h.indexOf("access_token=") >= 0) {
      var p = new URLSearchParams(h.slice(1));
      var t = p.get("access_token");
      if (t) {
        localStorage.setItem(TOK, t);
        try { history.replaceState(null, "", window.location.pathname + window.location.search); } catch (e) { }
        refreshEmail();   // best-effort: fill the display email from the verified token
      }
    }
  })();

  var _cfg = null;
  async function config() {
    if (_cfg) return _cfg;
    try { _cfg = await (await fetch("/api/auth/config")).json(); } catch (e) { _cfg = { mode: "mock" }; }
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

  function renderSignIn(host, onDone) {
    host.innerHTML =
      '<div class="card" style="margin-top:24px">' +
      '  <div style="font-weight:800;font-size:18px;text-align:center">Sign in to Rally</div>' +
      '  <div class="muted" style="text-align:center;margin:4px 0 14px">to score matches and rank players</div>' +
      '  <button class="btn" id="auGoogle">Continue with Google</button>' +
      '  <div class="muted" style="text-align:center;margin:12px 0 6px">or</div>' +
      '  <div id="auEmailBox">' +
      '    <input id="auEmail" type="email" placeholder="you@email.com" autocomplete="email">' +
      '    <button class="btn ghost" style="margin-top:8px" id="auSend">Continue with email</button>' +
      '  </div>' +
      '  <div id="auOtpBox" style="display:none">' +
      '    <div class="muted" id="auOtpNote" style="margin-bottom:6px"></div>' +
      '    <input id="auCode" inputmode="numeric" maxlength="6" placeholder="6-digit code">' +
      '    <button class="btn" style="margin-top:8px" id="auVerify">Verify</button>' +
      '  </div>' +
      '  <div class="err" id="auErr"></div>' +
      '</div>';
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
        host.querySelector("#auOtpNote").textContent =
          r.dev_code ? ("Dev mode — your code is " + r.dev_code) : ("Code sent to " + em);
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
    google: google, emailStart: emailStart, emailVerify: emailVerify,
    config: config, refreshEmail: refreshEmail, renderSignIn: renderSignIn
  };
})();
