"use strict";
/* Rally client auth (Task 4). Token in localStorage; sends Bearer on writes. Sign-in screen
   is inline (no popups): "Continue with Google" / "Continue with email" (6-digit OTP).
   Mock mode works with zero keys; email OTP also works against real Supabase. */
window.Auth = (function () {
  var TOK = "rally_token", EM = "rally_email";
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]); }); };

  function token() { return localStorage.getItem(TOK) || ""; }
  function email() { return localStorage.getItem(EM) || ""; }
  function signedIn() { return !!token(); }
  function headers() { return signedIn() ? { "Authorization": "Bearer " + token() } : {}; }
  function set(t, e) { localStorage.setItem(TOK, t); if (e) localStorage.setItem(EM, e); }
  function signOut() { localStorage.removeItem(TOK); localStorage.removeItem(EM); }

  async function _post(url, body) {
    var r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw (j.error || ("error " + r.status));
    return j;
  }
  async function google(em) { var r = await _post("/api/auth/google", { email: em }); set(r.token, r.email); return r; }
  async function emailStart(em) { return _post("/api/auth/email/start", { email: em }); }
  async function emailVerify(em, code) { var r = await _post("/api/auth/email/verify", { email: em, code: code }); set(r.token, r.email); return r; }

  // Inline sign-in screen. Calls onDone() when signed in.
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
    token: token, email: email, signedIn: signedIn, headers: headers,
    signOut: signOut, google: google, emailStart: emailStart, emailVerify: emailVerify,
    renderSignIn: renderSignIn
  };
})();
