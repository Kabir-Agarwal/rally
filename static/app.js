"use strict";
/* Rally v2 client. No popups anywhere. Auth-gated writes; instant DOM from the client engine
   (engine.js) with background sync (sync.js); poll for read views; 0-based rating display. */

// ---------- helpers ----------
const el = (h) => { const d = document.createElement("div"); d.innerHTML = h.trim(); return d.firstChild; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const av = (n) => `<span class="avatar">${esc((n || "?")[0]).toUpperCase()}</span>`;
const authHeaders = () => (window.Auth ? Auth.headers() : {});
// Game name (bold) with real name as subtext underneath. No empty gap when real name is blank.
function nameBlock(name, real) {
  return `<div class="pn"><div class="pn-game">${esc(name)}</div>` +
    (real ? `<div class="pn-real">${esc(real)}</div>` : "") + `</div>`;
}
const pBlock = (p) => nameBlock(p.name, p.real_name);
// clickable name block -> opens that player's page (Live cards, History cards)
const pLink = (p) => `<span class="plink" onclick="event.stopPropagation();openPlayer('${p.id}')">${pBlock(p)}</span>`;

// One transient bottom toast (create-on-demand, auto-dismiss). Not a tab restyle.
let _toastT = null;
function toast(msg) {
  let t = document.getElementById("toast");
  if (!t) { t = el(`<div id="toast" class="toast"></div>`); document.body.appendChild(t); }
  t.textContent = msg; t.classList.add("show");
  clearTimeout(_toastT); _toastT = setTimeout(() => t.classList.remove("show"), 3200);
}

async function api(url, body, method) {
  const m = method || (body ? "POST" : "GET");
  const opt = { method: m, headers: { ...authHeaders() } };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw (j.error || ("error " + r.status));
  return j;
}

// Global API URL with the active group FILTER (window.FILTER; null = everything the player has).
// G("/live") -> "/api/live" or "/api/live?group=CODE".
function G(path) {
  if (!window.FILTER) return "/api" + path;
  return "/api" + path + (path.includes("?") ? "&" : "?") + "group=" + encodeURIComponent(window.FILTER);
}

// Fail-open helper: resolve to `fallback` if `p` takes longer than `ms` or rejects, so a
// stalled network call can NEVER block the boot on the "Loading…" placeholder.
// NOTE: one-shot. On the boot path prefer `resilient()` below — a single short deadline treats a
// serverless cold start as a failure, which is exactly the bug this file used to have.
function raceTimeout(p, ms, fallback) {
  return Promise.race([
    Promise.resolve(p).catch(() => fallback),
    new Promise(res => setTimeout(() => res(fallback), ms || 4000)),
  ]);
}

const sleep = (ms) => new Promise(res => setTimeout(res, ms));

// ---------- retry: SLOW IS NOT BROKEN ----------
// Sentinel meaning "every attempt was exhausted". Distinct from null/undefined, which a server
// is allowed to return; only FAILED means "we could not reach the server at all".
const FAILED = { __rallyFailed: true };

// `make` must be a FUNCTION, not a promise — each attempt has to issue a NEW request. (The old
// code raced an already-started promise, so a "retry" could only ever re-await the same stall.)
function attempt(make, ms) {
  let timer = null;
  return Promise.race([
    Promise.resolve().then(make),
    new Promise((_, rej) => { timer = setTimeout(() => rej(new Error("timeout")), ms); }),
  ]).then(v => { clearTimeout(timer); return v; }, e => { clearTimeout(timer); throw e; });
}

// The single place the network budget lives.
// Rationale: a Vercel cold start costs ~1.5s before any of our code runs, mobile radios add
// hundreds of ms of wake-up + RTT, and the first request also pays token verification. A 4-6s
// one-shot deadline routinely lost that race on a phone's FIRST load — which is precisely why the
// app showed "Rally couldn't start" on first open and worked on reload (warm function).
const NET = { tries: 3, ms: 12000, backoff: [700, 2000] };
window.NET = NET;                    // exposed so test_boot.cjs can shrink the budget

// Retry with backoff and a GENEROUS per-attempt deadline before ever calling something broken.
async function resilient(make, opts) {
  const o = opts || {};
  const tries = o.tries || NET.tries;
  const ms = o.ms || NET.ms;                      // per attempt, not total
  const backoff = o.backoff || NET.backoff;
  for (let i = 0; i < tries; i++) {
    try {
      const v = await attempt(make, ms);
      if (o.onProgress) { try { o.onProgress(); } catch (e) { } }
      return v;
    } catch (e) {
      if (i < tries - 1) {
        if (o.onRetry) { try { o.onRetry(i + 1, tries); } catch (e2) { } }
        await sleep(backoff[Math.min(i, backoff.length - 1)]);
      }
    }
  }
  return FAILED;
}
// True when `v` is a real answer rather than the FAILED sentinel. (A function declaration, not a
// const arrow, so the Node boot tests can reach it on the sandbox global.)
function ok(v) { return v !== FAILED; }

// joined-groups memory (device-local); identity is server-side (player_links)
const LS = {
  groups() { try { return JSON.parse(localStorage.getItem("rally_groups") || "[]"); } catch (e) { return []; } },
  add(g) { const gs = LS.groups().filter(x => x.code !== g.code); gs.unshift(g); localStorage.setItem("rally_groups", JSON.stringify(gs)); },
};

// background sync queue (auth-aware fetch); status chip
const queue = window.SyncQueue ? new SyncQueue({
  fetch: (url, opt) => fetch(url, { ...opt, headers: { ...(opt.headers || {}), ...authHeaders() } }),
  onStatus: updateChip
}) : null;
function updateChip(s) {
  const c = document.getElementById("syncChip"); if (!c) return;
  c.textContent = s === "saving" ? "○ saving…" : "● synced";
  c.className = "syncchip " + (s === "saving" ? "saving" : "synced");
}
function enqueue(url, body) { return queue ? queue.push({ url, body }) : api(url, body); }

let ME = { signed_in: false, player_id: null, player_name: null, email: null };
function currentMe() { return ME; }   // accessor so the Node boot tests can inspect identity

// ---------- auth gate + identity ----------
function showSignInGate() {
  const tc = document.getElementById("tabContent");
  if (tc) tc.style.display = "none";
  document.querySelectorAll("#roBanner,#signinGate").forEach(n => n.remove());
  const gate = el(`<div id="signinGate"></div>`);
  document.querySelector(".app").appendChild(gate);
  Auth.renderSignIn(gate, () => location.reload());
}
// Header = WHO you are (left) + WHAT you're looking at (right).
// Left: game name with real name underneath, tappable to edit both (openNameEditor).
// Right: the group filter chip — the active group, or "All groups" when unfiltered.
function setHeaderName() {
  const game = document.getElementById("hdGame");
  const real = document.getElementById("hdReal");
  if (game) game.textContent = ME.player_name || "Rally";
  // Before identity resolves there is no name to show, so keep the subtitle rather than a gap.
  if (real) real.textContent = ME.player_name ? (ME.player_real_name || "") : "tennis scorer";
  const f = document.getElementById("hdFilterName");
  if (f) f.textContent = filterLabel();
}

// Tap the header name -> edit game name AND real name in one sheet. Same endpoint the Groups tab
// uses (/api/me/rename), so both places stay in agreement.
function openNameEditor() {
  if (!ME.player_id) return;                    // nothing to rename yet (not signed in / no player)
  closeNameEditor();
  const sh = el(`<div class="psheet" id="nameSheet" onclick="if(event.target.id=='nameSheet')closeNameEditor()">
    <div class="psheet-body card">
      <div style="font-weight:800;font-size:16px;margin-bottom:10px">Your name</div>
      <label class="fieldlab">Game name (what everyone sees)</label>
      <input id="hdGameField" maxlength="24" autocomplete="off" value="${esc(ME.player_name || "")}">
      <label class="fieldlab" style="margin-top:8px">Real name (optional)</label>
      <input id="hdRealField" maxlength="40" autocomplete="off" value="${esc(ME.player_real_name || "")}">
      <div class="err" id="hdNameErr"></div>
      <div class="row" style="margin-top:10px;gap:8px">
        <button class="btn sm ghost" style="flex:1" onclick="closeNameEditor()">Cancel</button>
        <button class="btn sm clay" style="flex:1" id="hdNameSave" onclick="saveHeaderName()">Save</button>
      </div>
      <div style="border-top:1px solid rgba(0,0,0,.08);margin-top:14px;padding-top:12px">
        <div style="font-weight:800;font-size:14px">Password sign-in</div>
        <div class="muted" style="margin:2px 0 8px">Optional. Lets you sign in with
          <b>${esc(ME.code || "your player ID")}</b> + a password instead of Google.</div>
        <input id="hdPwField" type="password" maxlength="72" autocomplete="new-password"
               placeholder="New password (min 8 characters)">
        <div class="err" id="hdPwErr"></div>
        <button class="btn sm" style="margin-top:8px" id="hdPwSave" onclick="saveHeaderPassword()">Set password</button>
      </div></div></div>`);
  document.body.appendChild(sh);
  const g = document.getElementById("hdGameField");
  if (g) { g.focus(); g.addEventListener("keydown", e => { if (e.key === "Enter") saveHeaderName(); }); }
  const r = document.getElementById("hdRealField");
  if (r) r.addEventListener("keydown", e => { if (e.key === "Enter") saveHeaderName(); });
}
function closeNameEditor() {
  const s = document.getElementById("nameSheet");
  if (s && s.parentNode) s.parentNode.removeChild(s);
}
// Set a password for player-ID sign-in. The password is sent once, over HTTPS, and the server
// keeps only a salted hash — it is never stored in the browser and never echoed back.
async function saveHeaderPassword() {
  const err = document.getElementById("hdPwErr");
  const field = document.getElementById("hdPwField");
  const btn = document.getElementById("hdPwSave");
  if (err) err.textContent = "";
  const pw = field ? field.value : "";
  if (!pw || pw.length < 8) { if (err) err.textContent = "password must be at least 8 characters"; return; }
  if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }
  try {
    await api("/api/auth/set-password", { password: pw });
    if (field) field.value = "";
    toast("Password set — you can sign in with " + (ME.code || "your player ID"));
    if (btn) { btn.disabled = false; btn.textContent = "Set password"; }
  } catch (e) {
    if (err) err.textContent = String(e);
    if (btn) { btn.disabled = false; btn.textContent = "Set password"; }
  }
}
async function saveHeaderName() {
  const err = document.getElementById("hdNameErr");
  if (err) err.textContent = "";
  const name = (document.getElementById("hdGameField") || {}).value;
  const real_name = (document.getElementById("hdRealField") || {}).value;
  if (!name || !name.trim()) { if (err) err.textContent = "game name is required"; return; }
  const btn = document.getElementById("hdNameSave");
  if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }     // no double-submit
  try {
    await api("/api/me/rename", { name: name.trim(), real_name });
    const me = await resilient(() => api("/api/me"), { tries: 2 });
    if (ok(me)) ME = me;
    else { ME.player_name = name.trim(); ME.player_real_name = (real_name || "").trim(); }
    setHeaderName();
    closeNameEditor();
    toast("Name updated");
    renderTab(CURRENT_TAB || "live");           // names appear all over the current tab
  } catch (e) {
    if (err) err.textContent = String(e);
    if (btn) { btn.disabled = false; btn.textContent = "Save"; }
  }
}

// No group gate any more: signed in -> full app; signed out -> sign-in screen.
async function authGate() {
  window.READONLY = false;
  if (window.Auth && Auth.signedIn()) { setHeaderName(); return true; }
  showSignInGate();
  return false;
}

async function ensureIdentity() {
  // A slow /api/me used to resolve to a FABRICATED {signed_in:false} after 4s — the app then
  // believed a signed-in user was signed out (no "you" card, pending joins dropped). Retry, and
  // if the server is genuinely unreachable leave ME untouched rather than inventing an answer.
  const r = await resilient(() => api("/api/me"), { onRetry: bootSlowNote });
  if (!ok(r)) return true;                        // unreachable: say nothing about identity
  ME = r;
  bootStep("identity");
  if (ME.signed_in && !ME.player_id) return await chooseName();   // first sign-in: pick a name
  return true;
}

// First sign-in: create the global player (game name + optional real name). One screen.
async function chooseName() {
  return new Promise((resolve) => {
    const tc = document.getElementById("tabContent");
    if (tc) tc.style.display = "none";
    const prefill = esc((ME && ME.provider_name) || "");
    const ov = el(`<div id="nameGate">
      <div class="card" style="margin-top:24px">
        <div style="font-weight:800;font-size:18px;text-align:center">Set up your player</div>
        <div class="muted" style="text-align:center;margin:4px 0 12px">You can change these any time.</div>
        <label class="fieldlab">Game name (what everyone sees)</label>
        <input id="nmField" placeholder="e.g. Ace" autocomplete="off" maxlength="24">
        <label class="fieldlab" style="margin-top:8px">Real name</label>
        <input id="nmReal" placeholder="optional" autocomplete="off" maxlength="40" value="${prefill}">
        <button class="btn" style="margin-top:10px" id="nmGo">Continue</button>
        <div class="err" id="nmErr"></div>
      </div></div>`);
    document.querySelector(".app").appendChild(ov);
    const err = ov.querySelector("#nmErr");
    ov.querySelector("#nmGo").onclick = async () => {
      err.textContent = "";
      const name = ov.querySelector("#nmField").value.trim();
      const real_name = ov.querySelector("#nmReal").value;
      if (!name) { err.textContent = "please enter a game name"; return; }
      try {
        await api("/api/me/claim", { name, real_name });
        ME = await api("/api/me");
        ov.remove(); if (tc) tc.style.display = ""; resolve(true);
      } catch (e) {
        // The claim can 409 ("you already have a player") when this account was already set up
        // somewhere else — e.g. the old email flow signed you in inside the mail app's browser,
        // you set up there, then came back here. That is not a failure: the player exists, so
        // pick it up and carry on instead of trapping the user in this overlay forever.
        try {
          const me = await api("/api/me");
          if (me && me.player_id) { ME = me; ov.remove(); if (tc) tc.style.display = ""; resolve(true); return; }
        } catch (_) { }
        err.textContent = e;
      }
    };
    ov.querySelector("#nmReal").addEventListener("keydown", e => { if (e.key === "Enter") ov.querySelector("#nmGo").click(); });
  });
}

// ---------- header switcher: a FILTER, not a gate. "All groups" + each of the player's groups.
async function openSwitcher() {
  const s = document.getElementById("switcher"); if (!s) return; s.classList.add("open");
  const list = document.getElementById("switcherList"); list.innerHTML = "";
  const pick = (code, name) => {
    window.FILTER = code; if (code) { window.GROUP = { code, name, is_public: true }; } else { window.GROUP = null; }
    setHeaderName(); closeSwitcher();
    history.replaceState({}, "", code ? "/g/" + code + "/live" : "/"); renderTab(CURRENT_TAB || "live");
  };
  const rowEl = (label, code, name, cur) => {
    const row = el(`<div class="grp"><span class="gname">${esc(label)}${cur ? ' <span class="tickmark">✓</span>' : ''}</span>${code ? `<span class="tag">${esc(code)}</span>` : ''}</div>`);
    row.onclick = () => pick(code, name); list.appendChild(row);
  };
  rowEl("All groups", null, null, !window.FILTER);
  try {
    const d = await api("/api/groups");
    (d.groups || []).forEach(g => rowEl(g.name, g.code, g.name, window.FILTER === g.code));
  } catch (e) { }
}
function closeSwitcher() { const s = document.getElementById("switcher"); if (s) s.classList.remove("open"); }

// ---------- polling (per-active-tab; cleared on tab switch) ----------
let POLLERS = [];
function poll(fn, ms) { fn(); const id = setInterval(() => { if (!document.hidden) fn(); }, ms || 3000); POLLERS.push(id); return id; }
function clearPollers() { POLLERS.forEach(clearInterval); POLLERS = []; }

// ---------- rating display (0-based) ----------
const disp = (elo0based) => (elo0based > 0 ? "+" : "") + elo0based;   // meta already 0-based
const dispFromElo = (elo) => { const v = Math.round(elo) - 1200; return (v > 0 ? "+" : "") + v; };

// ---------- shared: broadcast/scoreboard card (read-only) ----------
// Win-prob bar (mockup): a labels row, ONE segmented track, and a caption saying it updates
// live. 2-way = green fill on the line track; 3-way = green/gold/line segments in one bar.
function winBar(wp, kind) {
  if (!wp || !wp.length) return "";
  if (kind === "tt") {
    const cols = ["var(--live)", "var(--gold)", "var(--line)"];
    const labels = wp.map(w => `<span>${esc(w.label)} · ${w.pct}%</span>`).join("");
    const segs = wp.map((w, i) => `<span class="wpseg" style="width:${w.pct}%;background:${cols[i] || 'var(--line)'}"></span>`).join("");
    return `<div class="wpwrap"><div class="wplabels">${labels}</div>
      <div class="wptrack">${segs}</div>
      <div class="wpcap">updates live with every point, from ratings + games won</div></div>`;
  }
  const a = wp[0], b = wp[1];
  return `<div class="wpwrap">
    <div class="wplabels"><span>${esc(a.label)} · ${a.pct}%</span><span class="right">${b.pct}% · ${esc(b.label)}</span></div>
    <div class="wptrack"><span class="wpseg" style="width:${a.pct}%;background:var(--live)"></span></div>
    <div class="wpcap">updates live with every point, from ratings + current score</div></div>`;
}

function hhmm(iso) {
  if (!iso) return "";
  const d = new Date(iso.replace(" ", "T"));
  if (isNaN(d)) return "";
  let h = d.getHours(), m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "PM" : "AM"; h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}
function bhead(kindLabel, m) {
  const t = hhmm(m.started_at);
  return `<div class="bhead2"><span class="bkind">${kindLabel}${t ? ` · started ${t}` : ""}</span><span class="livepill">LIVE</span></div>`;
}
function broadcastCard(m) {
  if (m.kind === "tt") {
    const p = m.pairing;
    let strip = `<div class="ttstrip">` + m.tally.map(t => `<div class="ttcell">${pLink(t)}<b class="ttwins">${t.wins}</b></div>`).join("") + `</div>`;
    let line = p ? `<div class="server">Server 🎾 ${esc(p.server)} · ${esc(p.receiver)} Receiver</div>
      <div class="muted">Game ${m.game_no + 1} · ${esc(p.sitter)} sits out</div>` : "";
    return el(`<div class="bcast">${bhead("Triple threat", m)}${strip}${line}${winBar(m.win_prob, "tt")}${m.group ? `<div class="note">${esc(m.group)}</div>` : ""}</div>`);
  }
  const side = (arr) => arr.map(p => `<div class="bname">${p.id === m.server_id ? '🎾 ' : ''}${pLink(p)}</div>`).join("");
  let cols = m.sets.map(s => `<div class="setcol"><div class="setcell ${s.won1 ? 'won' : ''}">${s.g1}</div><div class="setcell ${s.won2 ? 'won' : ''}">${s.g2}</div></div>`).join("");
  let pts = (m.per_point && m.point_score) ? `<div class="ptsbox">${esc(m.point_score)}</div>` : "";
  return el(`<div class="bcast">
    ${bhead(m.kind.charAt(0).toUpperCase() + m.kind.slice(1), m)}
    <div class="brow"><div class="bteam">${side(m.side1)}</div><div class="bsets">${cols}</div>${pts}</div>
    <div class="brow"><div class="bteam">${side(m.side2)}</div></div>
    ${winBar(m.win_prob, m.kind)}${m.group ? `<div class="note">${esc(m.group)}</div>` : ""}</div>`);
}

// ================= LIVE =================
// A poller's FIRST load is patient (retries; a cold start must not look like a failure). Later
// refreshes are quick, and on failure they keep the data already on screen instead of wiping it —
// a dropped poll is not a reason to replace good data with an error.
let LIVE_LOADED = false;
function initLive() {
  LIVE_LOADED = false;
  poll(async () => {
    const first = !LIVE_LOADED;
    const d = await resilient(() => api(G("/live")),
      first ? { onRetry: bootSlowNote } : { tries: 1 });
    const host = document.getElementById("liveMatches"); if (!host) return;
    if (!ok(d)) {
      if (LIVE_LOADED) return;                                  // keep what's rendered
      host.innerHTML = `<div class="empty">Couldn't load live matches — <a href="#" onclick="initLive();return false">retry</a></div>`;
      return;
    }
    LIVE_LOADED = true;
    bootStep("live");
    _clearSlowNote();
    host.innerHTML = "";
    if (!d.matches.length) host.appendChild(el(`<div class="empty">No live matches. Start one in Log.</div>`));
    d.matches.forEach(m => host.appendChild(broadcastCard(m)));
    const pub = document.getElementById("publicWrap");
    if (!d.public.length) { pub.innerHTML = ""; }   // empty sections render NOTHING
    else {
      pub.innerHTML = `<div class="sec-title">From public groups — watch only</div>`;
      const box = el(`<div id="publicMatches"></div>`); pub.appendChild(box);
      d.public.forEach(m => box.appendChild(broadcastCard(m)));
    }
  });
}

// ================= RANKS =================
let RANK = { mode: "singles", scope: "group", data: null };
function toggleFunnel(id) { const p = document.getElementById(id); p.style.display = p.style.display === "block" ? "none" : "block"; }
function setRankOpt(kind, val, btn) {
  btn.parentElement.querySelectorAll("button").forEach(b => b.classList.remove("on")); btn.classList.add("on");
  RANK[kind] = val; loadRanks();
}
async function loadRanks() {
  const first = !RANK.data;
  const d = await resilient(() => api(G("/leaderboard?mode=" + RANK.mode)),
    first ? { onRetry: bootSlowNote } : { tries: 1 });
  if (!ok(d)) {
    if (RANK.data) return;                      // a dropped refresh must not wipe the board
    const host = document.getElementById("rankList");
    if (host) host.innerHTML = `<div class="empty">Couldn't load ranks — <a href="#" onclick="loadRanks();return false">retry</a></div>`;
    return;
  }
  RANK.data = d;
  bootStep("ranks");
  _clearSlowNote();
  renderRanks();
}
// relationship of ME to a player, in plain words (server sends r.rel: you/friend/sent/incoming/none)
function relLabel(rel) {
  return rel === "you" ? "you" : rel === "friend" ? "friend"
    : (rel === "sent" || rel === "incoming") ? "requested" : "not a friend";
}
// ONE row shape for the whole board. An under-5-matches player is the SAME row, greyed, with
// "N of 5" where a rank number would be — no separate provisional section.
function rankRow(r, mePid) {
  const you = r.id == mePid;
  const dot = r.live ? '<span class="dot pulse"></span>' : '<span class="dotspace"></span>';
  const tag = r.group ? `<span class="tag">${esc(r.group)}</span>` : "";
  const rating = dispFromEloRow(r);
  const v = r.rating - 1200;
  const cls = r.provisional ? "" : (v > 0 ? "pos" : v < 0 ? "neg" : "zero");
  const sub = r.provisional
    ? `${relLabel(r.rel)} · unranked until 5 matches`
    : relLabel(r.rel);
  return `<div class="lbrow ${you ? 'you' : ''} ${r.provisional ? 'prov' : ''}" onclick="openPlayerSheet('${r.id}')">
    <div class="rk">${r.provisional ? '–' : r.rank}</div>${av(r.name)}
    <div class="nm">${dot}${pBlock(r)}${tag}${you ? ' <span class="youpill">YOU</span>' : ''}<div class="tapstats">${esc(sub)}</div></div>
    <div class="rt ${cls}">${rating}${r.provisional ? ` <span class="pill">${r.n} of 5</span>` : ''}</div></div>`;
}
const dispFromEloRow = (r) => { const v = r.rating - 1200; return (v > 0 ? "+" : "") + v; };
// The board as ONE ordered list. Server sends `rows`; fall back to the older ranked+provisional
// pair so a stale cached payload still renders.
function allRankRows() {
  const d = RANK.data;
  if (!d) return [];
  return d.rows || (d.ranked || []).concat(d.provisional || []);
}
function renderRanks() {
  if (!RANK.data) return;
  const sl = document.getElementById("rankScopeLine");
  if (sl) sl.textContent = (RANK.mode === "doubles" ? "Doubles" : "Singles") + " · " + filterLabel();
  const q = (document.getElementById("rankSearch").value || "").toLowerCase();
  const all = allRankRows();
  const shown = all.filter(r => r.name.toLowerCase().includes(q));
  const yc = document.getElementById("youCard"); yc.innerHTML = "";
  if (ME.player_id) {
    const you = all.find(r => r.id == ME.player_id);
    if (you) yc.appendChild(el(`<div class="youcard" onclick="openPlayer('${you.id}')">${av(you.name)}
      <div style="flex:1">${pBlock(you)} <span class="youpill">YOU</span></div>
      <div>${you.provisional ? `${you.n} of 5` : "#" + you.rank} · <b>${dispFromEloRow(you)}</b></div></div>`));
  }
  // ONE list. Under-5 players are greyed rows inside it, not a section of their own.
  document.getElementById("rankList").innerHTML = shown.length
    ? shown.map(r => rankRow(r, ME.player_id)).join("")
    : `<div class="empty">${all.length ? "No players match that search." : "No players yet."}</div>`;
}
function initRanks() { loadRanks(); poll(async () => { await loadRanks(); }, 5000); }

// ---- Ranks bottom sheet: Name#CODE, rating + matches, See stats, Add friend (state = reality) ----
function _rankById(pid) {
  return allRankRows().find(r => r.id == pid) || null;
}
function openPlayerSheet(pid) {
  const r = _rankById(pid);
  if (!r) return openPlayer(pid);                 // no cached row -> straight to stats
  const rating = dispFromEloRow(r);
  let addBtn;                                      // state reflects the real relationship
  if (r.rel === "you") addBtn = "";               // your own row: no add button
  else if (r.rel === "friend") addBtn = `<span class="muted" style="flex:1;text-align:center">Already a friend</span>`;
  else if (r.rel === "sent") addBtn = `<span class="muted" style="flex:1;text-align:center">Friend request sent</span>`;
  else addBtn = `<button class="btn sm clay" style="flex:1" onclick="sheetAddFriend('${r.id}',this)">Add friend</button>`;
  const sh = el(`<div class="psheet" id="playerSheet" onclick="if(event.target.id=='playerSheet')closeSheet()">
    <div class="psheet-body card">
      <div class="row"><span class="avatar" style="width:40px;height:40px;font-size:17px;flex:0 0 auto">${esc((r.name[0] || '?').toUpperCase())}</span>
        <div style="flex:1"><div class="pn-game" style="font-size:16px">${esc(r.name)}<span class="muted" style="font-weight:800">#${esc(r.code || '')}</span></div>
          ${r.real_name ? `<div class="pn-real">${esc(r.real_name)}</div>` : ''}
          <div class="muted" style="margin-top:2px">${rating} · ${r.n} match${r.n === 1 ? '' : 'es'}</div></div></div>
      <div id="sheetErr" class="err"></div>
      <div class="row" style="margin-top:10px;gap:8px">
        <button class="btn sm ghost" style="flex:1" onclick="closeSheet();openPlayer('${r.id}')">See stats</button>
        ${addBtn}</div></div></div>`);
  document.body.appendChild(sh);
}
function closeSheet() { const s = document.getElementById("playerSheet"); if (s) s.remove(); }
async function sheetAddFriend(pid, btn) {
  const err = document.getElementById("sheetErr"); if (err) err.textContent = "";
  try {
    const rr = await api("/api/friend/request", { id: pid });
    btn.outerHTML = `<span class="muted" style="flex:1;text-align:center">${rr.status === "accepted" ? "Already a friend" : "Friend request sent"}</span>`;
    const row = _rankById(pid); if (row) row.rel = rr.status === "accepted" ? "friend" : "sent";  // row subtitle updates too
    renderRanks();
  } catch (e) { if (err) err.textContent = "Couldn't send: " + e; }   // never a dead tap
}

// ---------- funnel drawer (Ranks + History filters) ----------
const HIST_KIND_LABELS = { all: "All", singles: "Singles", doubles: "Doubles", tt: "Triple threat" };
const HIST_KIND_FROM = { "All": "all", "Singles": "singles", "Doubles": "doubles", "Triple threat": "tt" };
function scopeLabel(s) { return s === "everyone" ? "Everyone" : "This group"; }
// The active view is a group FILTER (or "All groups"); the old "This group" label was wrong now.
function filterLabel() { return window.FILTER && window.GROUP ? window.GROUP.name : "All groups"; }
function openFunnel(which) {
  const isR = which === "ranks";
  const modes = isR ? ["Singles", "Doubles"] : ["All", "Singles", "Doubles", "Triple threat"];
  const curMode = isR ? (RANK.mode === "doubles" ? "Doubles" : "Singles")
    : HIST_KIND_LABELS[HIST.kind];
  const curScope = scopeLabel(isR ? RANK.scope : HIST.scope);
  let mSel = curMode, sSel = curScope;
  const ov = el(`<div class="drawerwrap open">
    <div class="drawerbg" onclick="closeFunnel()"></div>
    <div class="drawer">
      <div style="font-weight:800;font-size:15px">Filters</div>
      <div class="fg"><div class="fglab">${isR ? "Mode" : "Kind"}</div><div id="fMode"></div></div>
      <div class="fg"><div class="fglab">Who</div><div id="fScope"></div></div>
      <button class="btn" id="fApply" style="margin-top:auto">Apply</button>
    </div></div>`);
  document.body.appendChild(ov);
  const fc = (host, opts, get, set) => {
    host.innerHTML = "";
    opts.forEach(o => {
      const b = el(`<button class="fcheck ${get() === o ? 'on' : ''}"><span class="fbox">${get() === o ? '✓' : ''}</span>${esc(o)}</button>`);
      b.onclick = () => { set(o); host.querySelectorAll(".fcheck").forEach(x => { x.classList.remove("on"); x.querySelector(".fbox").textContent = ""; }); b.classList.add("on"); b.querySelector(".fbox").textContent = "✓"; };
      host.appendChild(b);
    });
  };
  fc(ov.querySelector("#fMode"), modes, () => mSel, v => mSel = v);
  fc(ov.querySelector("#fScope"), ["This group", "Everyone"], () => sSel, v => sSel = v);
  ov.querySelector("#fApply").onclick = () => {
    const scope = sSel === "Everyone" ? "everyone" : "group";
    if (isR) { RANK.mode = mSel === "Doubles" ? "doubles" : "singles"; RANK.scope = scope; loadRanks(); }
    else { HIST.kind = HIST_KIND_FROM[mSel]; HIST.scope = scope; loadHistory(); }
    closeFunnel();
  };
}
function closeFunnel() { const d = document.querySelector(".drawerwrap"); if (d) d.remove(); }

// ================= GROUPS =================
// YOU card (mockup): avatar + game name + gold YOU badge + real-name subtext + "claimed on this
// phone" + a "Change" button that opens the game-name/real-name editor (Task 4). Email + sign-out
// live inside that editor so the card face stays as clean as the approved design.
function renderYouCard() {
  const host = document.getElementById("youCardG"); if (!host) return;
  const dn = ME.player_name || "—";
  const real = ME.player_real_name ? `<div class="pn-real">${esc(ME.player_real_name)}</div>` : "";
  // Your permanent public identity is Name#CODE. Copy pastes the code into someone's search; Share
  // sends a link that opens the app ready to friend you.
  const code = ME.code || "";
  const idLine = code
    ? `<div style="margin-top:2px;font-weight:800">${esc(dn)}<span class="muted" style="font-weight:800">#${esc(code)}</span>
         <button class="btn sm ghost" style="width:auto;padding:2px 8px;margin-left:6px" onclick="copyCode()">Copy</button>
         <button class="btn sm ghost" style="width:auto;padding:2px 8px" onclick="shareCode()">Share</button></div>`
    : "";
  host.innerHTML = `<div class="card">
    <div class="row">
      <span class="avatar" style="width:40px;height:40px;font-size:17px;flex:0 0 auto">${esc((dn[0] || "?").toUpperCase())}</span>
      <div style="flex:1"><div class="pn-game" style="font-size:16px">${esc(dn)} <span class="youpill">YOU</span></div>${real}
        <div class="muted">claimed on this phone</div></div>
      <button class="btn sm ghost" style="flex:0 0 auto" onclick="editName()">Change</button></div>
    ${idLine}<div class="note" id="youMsg"></div>
    <div id="editNameBox"></div></div>`;
}
function _youMsg(t) { const m = document.getElementById("youMsg"); if (m) { m.textContent = t; setTimeout(() => { if (m.textContent === t) m.textContent = ""; }, 2500); } }
function _copy(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch (e) { } ta.remove(); return Promise.resolve();
}
function copyCode() { if (!ME.code) return; _copy(ME.code).then(() => _youMsg("Code copied: " + ME.code)); }
function addLink() { return location.origin + "/?add=" + encodeURIComponent(ME.code || ""); }
function shareCode() {
  if (!ME.code) return;
  const url = addLink(), title = "Add me on Rally: " + (ME.player_name || "") + "#" + ME.code;
  if (navigator.share) { navigator.share({ title: "Rally", text: title, url }).catch(() => { }); }
  else { _copy(url).then(() => _youMsg("Link copied")); }
}
// Group join link — mirrors the friend /?add=CODE link. origin + /?join=<GROUP CODE>.
function joinLink(code) { return location.origin + "/?join=" + encodeURIComponent(code); }
function copyJoin(code) { _copy(joinLink(code)).then(() => toast("Join link copied")); }
function shareJoin(code) {
  const url = joinLink(code);
  if (navigator.share) navigator.share({ title: "Rally", text: "Join my group on Rally", url }).catch(() => { });
  else _copy(url).then(() => toast("Join link copied"));
}
function editName() {
  const box = document.getElementById("editNameBox");
  if (box.dataset.open) { box.dataset.open = ""; box.innerHTML = ""; return; }
  box.dataset.open = "1";
  box.innerHTML = `<div style="border-top:1px solid var(--line);margin-top:10px;padding-top:10px">
    <label class="fieldlab">Game name (what everyone sees)</label>
    <input id="enGame" maxlength="24" value="${esc(ME.player_name || "")}">
    <label class="fieldlab" style="margin-top:8px">Real name (optional)</label>
    <input id="enReal" maxlength="40" value="${esc(ME.player_real_name || "")}">
    <button class="btn" style="margin-top:10px" onclick="saveName()">Save</button>
    <div class="err" id="enErr"></div>
    <div class="muted" style="text-align:center;margin-top:10px">${esc(ME.email || "")} ·
      <a href="#" onclick="Auth.signOut();location.reload();return false">sign out</a></div></div>`;
}
async function saveName() {
  const err = document.getElementById("enErr"); err.textContent = "";
  const name = document.getElementById("enGame").value.trim();
  const real_name = document.getElementById("enReal").value;
  if (!name) { err.textContent = "game name is required"; return; }
  try {
    await api("/api/me/rename", { name, real_name });
    ME = await api("/api/me");
    setHeaderName(ME.group_name);
    renderYouCard();                                 // collapses the editor + shows the new name
  } catch (e) { err.textContent = e; }
}
async function initGroups() {
  renderYouCard();
  renderAddSomeone();
  renderFriends();
  renderGroupRows();
}

// ---- Task 2: Add someone (search by game name OR code -> friend request) ----
function renderAddSomeone() {
  const host = document.getElementById("addSomeone"); if (!host) return;
  host.innerHTML = `<div class="card">
    <input id="friendSearch" placeholder="Game name or player code" oninput="searchFriends()" autocomplete="off">
    <div id="friendSearchOut" style="margin-top:6px"></div></div>`;
  const code = new URLSearchParams(location.search).get("add");   // /?add=CODE deep link
  if (code) { host.querySelector("#friendSearch").value = code; searchFriends(); }
}
let _searchT = null;
function searchFriends() {
  clearTimeout(_searchT);
  _searchT = setTimeout(async () => {
    const inp = document.getElementById("friendSearch"), out = document.getElementById("friendSearchOut");
    if (!inp || !out) return;
    const q = inp.value.trim();
    if (!q) { out.innerHTML = ""; return; }
    let players;
    try { players = (await api("/api/players/search?q=" + encodeURIComponent(q))).players || []; }
    catch (e) { out.innerHTML = `<div class="muted">Couldn't search — try again</div>`; return; }
    players = players.filter(p => p.id !== ME.player_id);        // never offer yourself
    if (!players.length) { out.innerHTML = `<div class="muted">No player found for “${esc(q)}”.</div>`; return; }
    out.innerHTML = players.map(p => `<div class="lbrow" style="cursor:default;flex-wrap:wrap">
      ${av(p.name)}<div class="nm">${pBlock(p)}<span class="tag">#${esc(p.code)}</span></div>
      <button class="btn sm clay" style="width:auto;flex:0 0 auto" onclick="addFriend('${p.id}',this)">Add friend</button>
      <div class="err" style="flex-basis:100%" id="fre_${p.id}"></div></div>`).join("");
  }, 250);
}
async function addFriend(pid, btn) {
  const err = document.getElementById("fre_" + pid); if (err) err.textContent = "";
  try {
    const r = await api("/api/friend/request", { id: pid });
    btn.outerHTML = `<span class="muted" style="flex:0 0 auto">${r.status === "accepted" ? "friends ✓" : "requested"}</span>`;
    renderFriends();                                             // reflect a reciprocal auto-accept
  } catch (e) { if (err) err.textContent = "Couldn't send: " + e; }   // never a dead tap
}

// ---- Tasks 3 & 4: Friend requests (only when incoming) + Friends list (feeds the picker) ----
async function renderFriends() {
  const reqHost = document.getElementById("friendReqs"), listHost = document.getElementById("friendsList");
  let d;
  try { d = await api("/api/friends"); }
  catch (e) { if (listHost) listHost.innerHTML = `<div class="card"><div class="empty">Couldn't load friends — <a href="#" onclick="renderFriends();return false">retry</a></div></div>`; return; }
  if (reqHost) {
    reqHost.innerHTML = (d.pending && d.pending.length)
      ? `<div class="sec-title">Friend requests</div><div class="card" style="padding:2px 2px">` +
        d.pending.map(p => `<div class="lbrow" style="cursor:default;flex-wrap:wrap">${av(p.name)}
          <div class="nm">${pBlock(p)}<span class="tag">#${esc(p.code)}</span></div>
          <button class="btn sm ghost" style="width:auto;flex:0 0 auto" onclick="declineFriend('${p.id}')">Decline</button>
          <button class="btn sm clay" style="width:auto;flex:0 0 auto" onclick="acceptFriend('${p.id}')">Accept</button></div>`).join("") + `</div>`
      : "";
  }
  if (listHost) {
    listHost.innerHTML = (d.friends && d.friends.length)
      ? `<div class="card" style="padding:2px 2px">` + d.friends.map(p => `<div class="lbrow" onclick="openPlayer('${p.id}')">
          ${av(p.name)}<div class="nm">${pBlock(p)}<span class="tag">#${esc(p.code)}</span></div></div>`).join("") + `</div>`
      : `<div class="card"><div class="empty">No friends yet. Adding a friend is how you get someone into a match.</div></div>`;
  }
}
async function acceptFriend(pid) { try { await api("/api/friend/accept", { id: pid }); renderFriends(); } catch (e) { } }
async function declineFriend(pid) { try { await api("/api/friend/decline", { id: pid }); renderFriends(); } catch (e) { } }
// YOUR GROUPS: one card per group (from /api/groups) — 🎾 name, "code XXXX · private/public",
// tap to filter to that group, admin-only Make public/private.
// ATOMIC: fetch first, build off-screen, then swap in ONE operation. Never blank #groupRows before
// the data arrives — that empty gap was why deleting one group appeared to wipe the whole list.
async function renderGroupRows() {
  const host = document.getElementById("groupRows"); if (!host) return;
  let gs;
  try { gs = (await api("/api/groups")).groups || []; } catch (e) { gs = null; }
  if (!host.isConnected) return;
  if (gs === null) {                              // fetch failed: keep existing cards, offer a retry
    if (!host.children.length) host.innerHTML = `<div class="card"><div class="empty">Couldn't load your groups — <a href="#" onclick="renderGroupRows();return false">retry</a></div></div>`;
    return;
  }
  if (window.FILTER && !gs.some(g => g.code === window.FILTER)) { window.FILTER = null; window.GROUP = null; setHeaderName(); }
  const frag = document.createDocumentFragment();
  if (!gs.length) frag.appendChild(el('<div class="card"><div class="empty">No groups yet.</div></div>'));
  gs.forEach(g => {
    const cur = g.code === window.FILTER;
    const adminBtn = g.is_admin
      ? `<button class="btn sm ${g.is_public ? 'clay' : 'ghost'}" style="flex:0 0 auto" onclick="event.stopPropagation();flipPublic('${g.id}',${g.is_public ? 'true' : 'false'},this)">${g.is_public ? 'Make private' : 'Make public'}</button>` : '';
    const exitBtn = g.is_admin
      ? `<button class="btn sm danger" style="flex:0 0 auto" onclick="event.stopPropagation();deleteGroup('${g.id}')">Delete</button>`
      : `<button class="btn sm ghost" style="flex:0 0 auto" onclick="event.stopPropagation();leaveGroup('${g.id}')">Leave</button>`;
    const card = el(`<div class="card">
      <div class="row">
        <div style="flex:1">
          <div style="font-weight:800;font-size:14px">🎾 ${esc(g.name)}${cur ? ' <span class="curmark">· current</span>' : ''}</div>
          <div class="muted" style="margin-top:2px">code ${esc(g.code)} · ${g.is_public ? 'public' : 'private'}
            <button class="btn sm ghost" style="width:auto;padding:2px 8px;margin-left:6px" onclick="event.stopPropagation();copyJoin('${g.code}')">Copy</button>
            <button class="btn sm ghost" style="width:auto;padding:2px 8px" onclick="event.stopPropagation();shareJoin('${g.code}')">Share</button></div>
        </div>
      </div>
      <div class="row" style="margin-top:8px;gap:8px;justify-content:flex-end" id="ga_${g.id}">${adminBtn}${exitBtn}</div>
      <div class="note" id="gm_${g.id}"></div></div>`);
    card.style.cursor = "pointer";
    card.onclick = () => location.href = "/g/" + g.code + "/live";
    frag.appendChild(card);
  });
  host.replaceChildren(frag);                      // one-shot swap — no wipe, no empty flash
}
function _removeGroupCard(gid) {                    // instant feedback: drop just this card, keep the rest
  const box = document.getElementById("ga_" + gid);
  const card = box && box.closest(".card");
  if (card) card.remove();
}
// Leave a group (non-admin). The admin cannot silently orphan the group — the server rejects it
// and we surface the plain reason (hand admin over or delete).
async function leaveGroup(gid) {
  try { await api(`/api/group/${gid}/leave`, {}); _removeGroupCard(gid); renderGroupRows(); }
  catch (e) { const m = document.getElementById("gm_" + gid); if (m) m.textContent = e; }
}
// Delete a group — inline confirm that states matches are KEPT (no browser popups; no redesign).
function deleteGroup(gid) {
  const box = document.getElementById("ga_" + gid); if (!box) return;
  box.innerHTML = `<span class="muted" style="flex:1;text-align:left">Delete this group? Its matches are KEPT — only the group is removed.</span>
    <button class="btn sm ghost" style="flex:0 0 auto" onclick="event.stopPropagation();renderGroupRows()">Cancel</button>
    <button class="btn sm danger" style="flex:0 0 auto" onclick="event.stopPropagation();confirmDeleteGroup('${gid}')">Delete</button>`;
}
async function confirmDeleteGroup(gid) {
  try { await api(`/api/group/${gid}/delete`, {}); _removeGroupCard(gid); renderGroupRows(); }  // drop card now, reconcile atomically
  catch (e) { const m = document.getElementById("gm_" + gid); if (m) m.textContent = e; }
}
async function flipPublic(gid, cur, btn) {
  const next = !cur;
  try {
    await api(`/api/group/${gid}/public`, { is_public: next });
    btn.className = "btn sm " + (next ? "clay" : "ghost"); btn.textContent = next ? "Make private" : "Make public";
    btn.setAttribute("onclick", `event.stopPropagation();flipPublic('${gid}',${next},this)`);
    const sub = btn.closest(".card").querySelector(".muted");
    if (sub) sub.textContent = sub.textContent.replace(/(public|private)$/, next ? "public" : "private");
  } catch (e) { }
}
// tap-to-expand create / join (mockup): the card shows "+ …" buttons that reveal an input row.
function toggleCreate() {
  const host = document.getElementById("createRow");
  host.innerHTML = `<div class="row"><input id="newGroupName" placeholder="Group name" autofocus>
    <button class="btn sm" id="createBtn" style="flex:0 0 auto" onclick="createGroup()">Create</button></div><div id="createOut" class="note"></div>`;
  const inp = host.querySelector("#newGroupName");
  inp.focus(); inp.addEventListener("keydown", e => { if (e.key === "Enter") createGroup(); });
}
function toggleJoin() {
  const host = document.getElementById("joinRow");
  host.innerHTML = `<div class="row"><input id="joinCode2" maxlength="6" placeholder="Group code" style="text-transform:uppercase" autofocus>
    <button class="btn sm clay" style="flex:0 0 auto" onclick="joinGroup()">Join</button></div>`;
  const inp = host.querySelector("#joinCode2");
  inp.focus(); inp.addEventListener("keydown", e => { if (e.key === "Enter") joinGroup(); });
}
async function createGroup() {
  const btn = document.getElementById("createBtn");
  const name = document.getElementById("newGroupName").value.trim(); const out = document.getElementById("createOut");
  if (!name) { out.textContent = "name required"; return; }
  if (btn) { if (btn.disabled) return; btn.disabled = true; btn.textContent = "Creating…"; }  // in-flight guard: a double tap can't fire two creates
  out.textContent = "";
  try {
    const g = await api("/api/group/create", { name }); LS.add(g);
    // The new group shows EXACTLY ONCE — in Your Groups (with its code + Copy/Share). The old
    // "✔ created / share this code" card in #justCreated was a SECOND card for the same group
    // stacked right above the list; that was the "duplicate". No optimistic insert exists.
    document.getElementById("createRow").innerHTML = `<button class="btn ghost sm" onclick="toggleCreate()">+ Create a group</button>`;
    await renderGroupRows();
    toast(`Created ${g.name} — code ${g.code}`);
  } catch (e) { out.textContent = e; if (btn) { btn.disabled = false; btn.textContent = "Create"; } }
}
async function joinGroup() {
  const code = document.getElementById("joinCode2").value.trim().toUpperCase(); const out = document.getElementById("joinOut2"); out.textContent = "";
  try { const g = await api("/api/group/join", { code }); LS.add(g); location.href = "/g/" + g.code + "/live"; }
  catch (e) { out.textContent = e; }
}

// ================= HISTORY =================
let HIST = { kind: "all", scope: "group" };
function setHistOpt(kind, val, btn) { btn.parentElement.querySelectorAll("button").forEach(b => b.classList.remove("on")); btn.classList.add("on"); HIST[kind] = val; loadHistory(); }
async function loadHistory() {
  const sl = document.getElementById("histScopeLine");
  if (sl) sl.textContent = "· " + HIST_KIND_LABELS[HIST.kind] + " · " + filterLabel();
  const host = document.getElementById("historyList");
  // Never sit on "Loading…", but retry first — a cold start is not an error state.
  const d = await resilient(() => api(G("/history")), { onRetry: bootSlowNote });
  if (!host) return;
  if (!ok(d)) { host.innerHTML = `<div class="empty">Couldn't load history — <a href="#" onclick="loadHistory();return false">retry</a></div>`; return; }
  bootStep("history");
  _clearSlowNote();
  host.innerHTML = "";
  try {
    let matches = d.matches || [];
    if (HIST.kind !== "all") matches = matches.filter(m => m.kind === HIST.kind);
    if (!matches.length) { host.innerHTML = `<div class="empty">No finished matches.</div>`; return; }
    matches.forEach(m => host.appendChild(historyCard(m)));
  } catch (e) {
    host.innerHTML = `<div class="empty">Couldn't render history — <a href="#" onclick="loadHistory();return false">retry</a></div>`;
  }
}
function teamBlocks(arr) { return arr.map(pLink).join('<span class="amp">&</span>'); }
function matchTitle(m) {
  if (m.kind === "tt") return `<div class="side">${m.rotation.map(pLink).join('<span class="amp">·</span>')}</div>`;
  const w1 = m.winner_side === 1, w2 = m.winner_side === 2;
  return `<div class="side ${w1 ? 'winr' : ''}">${teamBlocks(m.side1)}${w1 ? ' 🏆' : ''}</div>
    <div class="vs">vs</div><div class="side ${w2 ? 'winr' : ''}">${teamBlocks(m.side2)}${w2 ? ' 🏆' : ''}</div>`;
}
function historyCard(m) {
  const when = esc((m.played_on || "").replace("T", " "));
  const title = matchTitle(m);
  let sets = m.kind === "tt"
    ? `<div class="ttstrip">${m.tally.map(t => `<div class="ttcell">${pBlock(t)}<b class="ttwins">${t.wins}</b></div>`).join("")}</div>`
    : `<div class="sheet">${m.sets.map(s => `<div class="setcol"><div class="setcell ${s.won1 ? 'won' : ''}">${s.g1}</div><div class="setcell ${s.won2 ? 'won' : ''}">${s.g2}</div></div>`).join("")}</div>`;
  const story = m.story ? storyLine(m.story) : "";
  const card = el(`<div class="match">
    <div class="mtitle">${title}</div>${sets}
    <div class="note">${m.kind.toUpperCase()} · <span class="whenlbl">${when}</span>
      <button class="editdt" title="edit date/time">✎</button></div>
    <div class="dtedit" style="display:none"><input type="datetime-local" class="dtin">
      <button class="btn sm" >Save</button></div>${story}</div>`);
  const editBtn = card.querySelector(".editdt");
  editBtn.onclick = () => { const e = card.querySelector(".dtedit"); e.style.display = e.style.display === "flex" ? "none" : "flex"; e.style.gap = "6px"; e.querySelector(".dtin").value = toLocalInput(m.played_on); };
  card.querySelector(".dtedit .btn").onclick = async () => {
    const v = card.querySelector(".dtin").value; if (!v) return;
    try {
      await api(G("/match/" + m.id + "/date"), { played_on: v.replace("T", " ") });
      card.querySelector(".whenlbl").textContent = v.replace("T", " ");
      card.querySelector(".dtedit").style.display = "none";
    } catch (e) { }
  };
  return card;
}
function toLocalInput(s) { if (!s) return ""; s = s.replace(" ", "T"); return s.length >= 16 ? s.slice(0, 16) : s; }
function storyLine(s) {
  let bits = [];
  if (s.holds || s.breaks) bits.push(`held ${s.holds}, broke ${s.breaks}`);
  if (s.saved_game_points) bits.push(`saved ${s.saved_game_points} game pts`);
  if (s.deuce_points) bits.push(`${s.deuce_points} deuce pts`);
  if (s.longest_streak >= 4) bits.push(`${s.longest_streak}-pt run`);
  return bits.length ? `<div class="note">🎾 Live-scored · ${bits.join(" · ")}</div>` : "";
}
function initHistory() { loadHistory(); }

// ================= PLAYER (in-app overlay) =================
let PLAYER_OPEN = false;
async function openPlayer(pid) {
  const ov = document.getElementById("playerOverlay");
  PLAYER_OPEN = true;
  ov.style.display = "block";
  ov.innerHTML = `<div class="card"><div class="empty">Loading…</div></div>`;
  history.pushState({ player: pid }, "", (window.FILTER ? "/g/" + window.FILTER : "") + "/player/" + pid);
  try {
    const p = await api(G("/player/" + pid));
    renderPlayer(ov, p);
  } catch (e) { ov.innerHTML = `<div class="card"><div class="empty">Could not load player.</div><button class="btn ghost sm" onclick="closePlayer()">← Back</button></div>`; }
}
function closePlayer(silent) {
  const ov = document.getElementById("playerOverlay");
  if (ov) { ov.style.display = "none"; ov.innerHTML = ""; }
  PLAYER_OPEN = false;
  if (!silent) { if (history.state && history.state.player) history.back(); }
}
function renderPlayer(ov, p) {
  const you = ME && ME.player_id === p.id;
  const l5 = (p.last5 || []).map(r => `<b style="color:${r === 'W' ? 'var(--live)' : '#c0392b'}">${r}</b>`).join(" ");
  const pairs = (p.pairs || []).map(pr =>
    `<div class="lbrow" style="cursor:default"><div class="nm">with ${esc(pr.partner)}</div>
      <div class="rt">${pr.rating - 1200 >= 0 ? '+' : ''}${pr.rating - 1200}</div>${pr.provisional ? `<span class="pill">${pr.n}/3</span>` : ''}</div>`).join("");
  const serve = p.serve || {};
  const serveCard = serve.live_matches
    ? `<div class="row"><div class="setcol"><div class="muted">Hold %</div><div style="font-size:20px;font-weight:900">${serve.hold_pct == null ? '—' : serve.hold_pct}</div></div>
        <div class="setcol"><div class="muted">Break %</div><div style="font-size:20px;font-weight:900">${serve.break_pct == null ? '—' : serve.break_pct}</div></div></div>
        <div class="note">from ${serve.live_matches} live-scored match(es) · return stats team-level for doubles</div>`
    : `<div class="muted">No live-scored matches yet.</div>`;
  const matches = (p.matches || []).length
    ? p.matches.map(m => historyCardStatic(m).outerHTML).join("")
    : `<div class="empty">No matches yet.</div>`;
  ov.innerHTML = `
    <div style="margin:12px 16px 0"><button class="btn ghost sm" onclick="closePlayer()">← Ranks</button></div>
    <div class="card"><div class="side" style="font-size:18px;align-items:flex-start">
      ${av(p.name).replace('avatar"', 'avatar" style="width:34px;height:34px;font-size:15px"')}
      <div class="pn"><div class="pn-game" style="font-size:20px">${esc(p.name)}${p.live ? '<span class="dot pulse"></span>' : ''}${you ? ' <span class="youpill">YOU</span>' : ''}</div>
        ${p.real_name ? `<div class="pn-real">${esc(p.real_name)}</div>` : ''}</div></div>
      <div class="muted" style="margin-top:6px">${p.wins}W · ${p.losses}L · last 5: ${l5 || '—'}</div>
      <div class="row" style="margin-top:10px">
        <div class="setcol"><div class="muted">Singles</div><div style="font-size:22px;font-weight:900">${p.singles - 1200 >= 0 ? '+' : ''}${p.singles - 1200}</div>${p.singles_prov ? `<span class="pill">${p.singles_n} of 5</span>` : ''}</div>
        <div class="setcol"><div class="muted">Doubles</div><div style="font-size:22px;font-weight:900">${p.doubles - 1200 >= 0 ? '+' : ''}${p.doubles - 1200}</div>${p.doubles_prov ? `<span class="pill">${p.doubles_n} of 5</span>` : ''}</div></div></div>
    ${pairs ? `<div class="sec-title">Pair ratings</div><div class="card" style="padding:6px 12px">${pairs}</div>` : ''}
    <div class="sec-title">Serve &amp; return</div><div class="card">${serveCard}</div>
    <div class="sec-title">Matches</div><div class="card" style="padding:6px 12px">${matches}</div>`;
}
function historyCardStatic(m) {
  const when = esc((m.played_on || "").replace("T", " "));
  const title = matchTitle(m);
  const sets = m.kind === "tt"
    ? `<div class="ttstrip">${m.tally.map(t => `<div class="ttcell">${pBlock(t)}<b class="ttwins">${t.wins}</b></div>`).join("")}</div>`
    : `<div class="sheet">${m.sets.map(s => `<div class="setcol"><div class="setcell ${s.won1 ? 'won' : ''}">${s.g1}</div><div class="setcell ${s.won2 ? 'won' : ''}">${s.g2}</div></div>`).join("")}</div>`;
  return el(`<div class="match"><div class="mtitle">${title}</div>${sets}<div class="note">${m.kind.toUpperCase()} · ${when}</div></div>`);
}

// ================= SPA ROUTER =================
const TAB_SKELETONS = {
  live: `<div class="sec-title">Live now</div><div id="liveMatches"><div class="empty">Loading…</div></div><div id="publicWrap"></div>`,
  leaderboard: `<div class="row" style="margin:12px 16px 0">
      <input id="rankSearch" placeholder="Search players…" oninput="renderRanks()">
      <button class="funnelbtn" onclick="openFunnel('ranks')">▼</button></div>
    <div id="rankScopeLine" class="scopeline"></div>
    <div id="youCard"></div>
    <div id="rankList" class="card" style="padding:2px 2px"><div class="empty">Loading…</div></div>`,
  log: `<div id="logRoot"><div class="empty">Loading…</div></div>`,
  groups: `<div class="sec-title">You</div><div id="youCardG"></div>
    <div class="sec-title">Add someone</div><div id="addSomeone"></div>
    <div id="friendReqs"></div>
    <div class="sec-title">Friends</div><div id="friendsList"></div>
    <div class="sec-title">Your groups</div><div id="groupRows"></div>
    <div class="card">
      <div id="createRow"><button class="btn ghost sm" onclick="toggleCreate()">+ Create a group</button></div>
      <div style="height:8px"></div>
      <div id="joinRow"><button class="btn ghost sm" onclick="toggleJoin()">+ Join another group</button></div>
      <div id="joinOut2" class="err"></div></div>`,
  history: `<div class="row" style="margin:12px 16px 0">
      <div class="sec-title" style="margin:0;flex:1">History <span id="histScopeLine" class="scopeinline"></span></div>
      <button class="funnelbtn" onclick="openFunnel('hist')">▼</button></div>
    <div id="historyList"><div class="empty">Loading…</div></div>`,
};
// Lazy wrappers: initLog lives in log.js, which is NOT loaded on the landing page. Referencing
// it directly here would throw at load and crash the whole boot. Arrows defer the lookup to
// call time (only ever on a group page, where log.js is present).
const TAB_INIT = {
  live: (r) => initLive(r), leaderboard: (r) => initRanks(r), log: (r) => initLog(r),
  groups: (r) => initGroups(r), history: (r) => initHistory(r),
};
const TAB_URL = { live: "live", leaderboard: "leaderboard", log: "log", groups: "groups", history: "history" };
const PANELS = {};
let CURRENT_TAB = null;

function setActiveNav(tab) {
  document.querySelectorAll("#tabBar button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
}
function panelFor(tab) {
  if (PANELS[tab]) return PANELS[tab];
  const box = document.createElement("div");
  box.className = "panel";
  if (window.READONLY && tab === "log") {
    box.innerHTML = `<div class="card" style="text-align:center"><div style="font-weight:800">Sign in to score</div>
      <div class="muted" style="margin:6px 0 10px">Scoring, starting matches and joining are for signed-in players.</div>
      <button class="btn" onclick="showSignInGate()">Sign in</button></div>`;
    PANELS[tab] = { el: box, inited: true, gate: true };
  } else {
    box.innerHTML = TAB_SKELETONS[tab];
    PANELS[tab] = { el: box, inited: false };
  }
  document.getElementById("tabContent").appendChild(box);
  return PANELS[tab];
}
function renderTab(tab) {
  clearPollers();
  closePlayer(true);
  const p = panelFor(tab);
  Object.keys(PANELS).forEach(k => PANELS[k].el.style.display = (k === tab ? "" : "none"));
  setActiveNav(tab);
  CURRENT_TAB = tab;
  if (!p.gate && TAB_INIT[tab]) TAB_INIT[tab](p.inited);   // pass whether this is a refresh
  p.inited = true;
}
function switchTab(tab) {
  if (tab === CURRENT_TAB && !PLAYER_OPEN) return;
  history.pushState({ tab }, "", (window.FILTER ? "/g/" + window.FILTER + "/" : "/") + TAB_URL[tab]);
  renderTab(tab);
}
function routeFromPath() {
  const parts = location.pathname.split("/");            // /g/<code>/<tab>[/player/<id>] ...
  const i = parts.indexOf("player");
  if (i >= 0 && parts[i + 1]) { renderTab(CURRENT_TAB || "leaderboard"); openPlayerNoPush(+parts[i + 1]); return; }
  const seg = parts[3] || "live";
  const tab = TAB_URL[seg] ? seg : "live";
  renderTab(tab);
}
async function openPlayerNoPush(pid) {   // for popstate/deep-link: render without pushing state
  const ov = document.getElementById("playerOverlay");
  PLAYER_OPEN = true; ov.style.display = "block"; ov.innerHTML = `<div class="card"><div class="empty">Loading…</div></div>`;
  try { renderPlayer(ov, await api(G("/player/" + pid))); } catch (e) { ov.innerHTML = `<div class="card"><div class="empty">Could not load player.</div></div>`; }
}
window.addEventListener("popstate", () => {
  if (PLAYER_OPEN && !(history.state && history.state.player)) { closePlayer(true); return; }
  routeFromPath();
});

// ---------- boot (fail-open: never stuck on "Loading…") ----------
// If a token exists, ask the server if the session is real. A definitive "no" (signed_in:false)
// clears the stale token. A timeout/error does NOT nuke a possibly-valid token — the boot just
// fails open to the sign-in view. Bounded by raceTimeout so it can't hang.
function _fetchMe() {
  // Retries, so a slow answer is never mistaken for "couldn't tell". Only a DEFINITIVE
  // signed_in:false may sign the user out, and that can only come from a real server reply.
  return resilient(
    () => fetch("/api/auth/me", { headers: Auth.headers() }).then(r => (r.ok ? r.json() : null)),
    { onRetry: bootSlowNote }).then(v => (ok(v) ? v : null));
}
async function staleTokenGuard() {
  if (!(window.Auth && Auth.signedIn())) return;
  let me = await _fetchMe();
  bootStep("token-guard");
  if (!(me && me.signed_in === false)) return;          // valid, or couldn't tell (fail open)
  // Server rejected the token. If a refresh token exists, try ONCE to renew (Task 3: sessions
  // shouldn't die every hour) and re-check before giving up. Renewal is a round trip to Supabase,
  // so it gets a real budget too — a slow renewal is not a failed renewal.
  if (Auth.refreshToken && Auth.refreshToken()) {
    const refreshed = await resilient(() => Auth.refreshSession(), { tries: 2 });
    if (ok(refreshed) && refreshed) { me = await _fetchMe(); if (!(me && me.signed_in === false)) return; }
  }
  // Definitively rejected. If this token was captured during THIS sign-in attempt, say why
  // instead of silently bouncing back to the card (Task 2). A plain expired token stays silent.
  const lr = Auth.lastReturn && Auth.lastReturn();
  if (lr && lr.ok === true) {
    Auth.recordReturn({ ok: false, message: "Signed in with Google, but the server rejected the session." });
  }
  Auth.signOut();
}
function _errorCard(host) {
  if (!host) return;
  host.innerHTML = `<div class="card" style="text-align:center;margin-top:24px">
    <div style="font-weight:800">Rally couldn't start</div>
    <div class="muted" style="margin:6px 0 10px">tap to retry</div>
    <button class="btn" onclick="location.reload()">Reload</button></div>`;
}
function failOpen() {
  if (!(window.Auth && Auth.signedIn())) {
    try { showSignInGate(); } catch (e) { _errorCard(document.getElementById("tabContent")); }
  } else {
    _errorCard(document.getElementById("tabContent"));
  }
}

// ---------- boot watchdog ----------
// The old backstop was `setTimeout(failOpen, 4500)`: a blind wall-clock deadline that fired even
// while boot was making perfectly good progress. On a phone's first load (cold serverless start +
// mobile RTT) it fired essentially every time, which IS the "Rally couldn't start" card the user
// saw — and a reload worked because the function was then warm. Worse, Auth.config()'s own retry
// budget (3 x 10s) could never finish inside 4.5s, so that fix could never actually take effect.
//
// The replacement watches PROGRESS, not the clock: it only gives up if boot has reached no new
// milestone for BOOT.stallMs, or has been going for BOOT.maxMs overall. Slow is not broken.
const BOOT = {
  stallMs: 25000,      // no milestone reached for this long => genuinely stuck
  maxMs: 75000,        // absolute ceiling, so boot can never hang forever
  slowNoteMs: 5000,    // after this, TELL the user it's slow (NOT that it failed)
  tickMs: 1000,        // how often the watchdog looks at progress
};
window.BOOT = BOOT;               // exposed so test_boot.cjs can shrink the thresholds
let BOOT_T0 = 0, BOOT_MARK = 0, BOOT_DONE = false, BOOT_WD = null, BOOT_NOTED = false;

function bootStep(label) { BOOT_MARK = Date.now(); }   // label kept for debugging/readability

// An honest "still working" state. NOT an error.
// It is appended as its OWN node and never writes into #tabContent: that container holds the tab
// PANELS, and overwriting its innerHTML detached the already-rendered panel (PANELS still cached
// the orphan, so renderTab would not rebuild it) and left the app blank on a slow connection.
function bootSlowNote() {
  if (BOOT_DONE || BOOT_NOTED) return;
  if (Date.now() - BOOT_T0 < BOOT.slowNoteMs) return;
  if (document.getElementById("bootSlow")) return;
  const host = document.querySelector(".app") || document.body;
  if (!host) return;
  BOOT_NOTED = true;
  host.appendChild(el(`<div class="card" id="bootSlow" style="text-align:center">
    <div style="font-weight:800">Starting Rally…</div>
    <div class="muted" style="margin-top:6px">slow connection — still trying</div></div>`));
}
function _clearSlowNote() {
  const n = document.getElementById("bootSlow");
  if (n && n.parentNode) n.parentNode.removeChild(n);
  BOOT_NOTED = false;
}
function bootWatchdog() {
  if (BOOT_DONE) return;
  const now = Date.now();
  if (now - BOOT_T0 > BOOT.slowNoteMs) bootSlowNote();
  if (now - BOOT_MARK > BOOT.stallMs || now - BOOT_T0 > BOOT.maxMs) {
    BOOT_DONE = true;
    clearInterval(BOOT_WD);
    failOpen();
  }
}
// /?join=CODE deep link. Persist the code IMMEDIATELY (before any sign-in redirect that would
// drop the query), then complete it once a signed-in player exists — so signing in on the way
// through never loses the code.
function storePendingJoin() {
  const code = new URLSearchParams(location.search).get("join");
  if (code) { try { localStorage.setItem("rally_pending_join", code); } catch (e) { } }
}
async function completePendingJoin() {
  let code; try { code = localStorage.getItem("rally_pending_join"); } catch (e) { }
  if (!code) return;
  try { localStorage.removeItem("rally_pending_join"); } catch (e) { }
  try {
    const g = await api("/api/group/join", { code });    // public -> joined; private -> requested
    if (g.joined) {
      LS.add(g); window.FILTER = g.code; window.GROUP = { code: g.code, name: g.name, is_public: true };
      setHeaderName(); history.replaceState({}, "", "/g/" + g.code + "/live"); renderTab("live");
      toast("Joined " + g.name);
    } else {
      toast("Requested to join " + g.name + " — waiting for the admin to admit you.");
    }
  } catch (e) { toast(String(e)); }        // unknown code -> "no group with that code" (never silent)
}
async function boot() {
  storePendingJoin();
  await staleTokenGuard();
  if (!(await authGate())) return;         // signed out -> sign-in screen (join code kept for after)
  bootStep("auth-gate");
  let initTab = (window.INIT && TAB_URL[window.INIT.tab]) ? window.INIT.tab : "live";
  if (new URLSearchParams(location.search).get("add")) initTab = "groups";   // /?add=CODE -> Add someone
  // Render what we have NOW: paint the tab immediately (its data fetch fires right away) and resolve
  // identity IN PARALLEL, instead of blocking first paint on a second sequential token-verify.
  // ensureIdentity() is already internally bounded + retrying, so it is NOT wrapped in a deadline
  // here — wrapping it was a second "slow == broken" trap (10s and identity was silently dropped).
  const idP = ensureIdentity().catch(() => true);
  _clearSlowNote();
  renderTab(initTab);
  setActiveNav(initTab);
  bootStep("first-paint");
  if (window.INIT && window.INIT.player) openPlayerNoPush(window.INIT.player);
  await idP;                               // a new user needs a name -> chooseName shows (tab already up)
  setHeaderName();                         // the header shows ME, so it can only fill in once ME is known
  if (ME.player_id && CURRENT_TAB === "leaderboard") renderTab("leaderboard");  // fill the "you" card once known
  if (ME.player_id) await completePendingJoin();   // /?join=CODE, now that we have a signed-in player
}
let _booted = false;
function startBoot() {
  if (_booted) return;                    // run exactly once, whichever trigger fires first
  _booted = true;
  BOOT_T0 = BOOT_MARK = Date.now();
  // Progress-aware watchdog instead of a blind deadline (see bootWatchdog). It only declares
  // failure if boot genuinely stops advancing; a slow network just gets a "still trying" note.
  BOOT_WD = setInterval(bootWatchdog, BOOT.tickMs);
  const finish = () => { BOOT_DONE = true; clearInterval(BOOT_WD); _clearSlowNote(); };
  boot().then(finish).catch(() => { finish(); failOpen(); });   // a thrown error IS broken
}
// Belt-and-suspenders: this script may run before OR after DOMContentLoaded, and in some
// embedded browsers the event doesn't reach a late-added listener. Trigger from every angle;
// the once-guard makes sure boot runs a single time.
// RALLY_NO_AUTOBOOT lets test_boot.cjs drive startBoot() itself instead of racing these timers.
if (!window.RALLY_NO_AUTOBOOT) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startBoot);
  window.addEventListener("load", startBoot);
  setTimeout(startBoot, 0);
}

// ---------- landing ----------
function initLanding() {
  const host = document.getElementById("landingContent");
  if (!(window.Auth && Auth.signedIn())) { Auth.renderSignIn(host, () => location.reload()); return; }
  renderLanding(host);                                  // render immediately — never block on a fetch
  if (!Auth.email()) {                                  // fill email in the background (after Google OAuth)
    resilient(() => Auth.refreshEmail(), { tries: 2 }).then(() => { if (Auth.email()) renderLanding(host); });
  }
}
// Landing is group-agnostic (no per-group player yet), so its YOU card shows the signed-in
// email + Sign out in place of the game-name/Change editor that the in-group Groups tab has.
function renderLanding(host) {
  const em = Auth.email() || "";
  host.innerHTML = `
    <div class="sec-title">You</div>
    <div class="card"><div class="row">
      <span class="avatar" style="width:40px;height:40px;font-size:17px;flex:0 0 auto">${esc((em[0] || "?").toUpperCase())}</span>
      <div style="flex:1"><div class="pn-game" style="font-size:15px">${em ? esc(em) : "Signed in"}</div>
        <div class="muted">signed in on this phone</div></div>
      <button class="btn sm ghost" style="flex:0 0 auto" onclick="Auth.signOut();location.reload()">Sign out</button></div></div>
    <div id="myGroups"></div>
    <div id="landCreated"></div>
    <div class="card">
      <div id="lCreateRow"><button class="btn ghost sm" onclick="landToggleCreate()">+ Create a group</button></div>
      <div style="height:8px"></div>
      <div id="lJoinRow"><button class="btn ghost sm" onclick="landToggleJoin()">+ Join a group</button></div>
      <div class="err" id="joinErr"></div></div>`;
  renderMyGroups();
}
function renderMyGroups() {
  const host = document.getElementById("myGroups"); if (!host) return;
  const gs = LS.groups(); if (!gs.length) { host.innerHTML = ""; return; }
  host.innerHTML = `<div class="sec-title">Your groups</div>` +
    gs.map(g => `<div class="card" style="cursor:pointer" onclick="location.href='/g/${g.code}/live'">
      <div style="font-weight:800;font-size:14px">🎾 ${esc(g.name)}</div>
      <div class="muted" style="margin-top:2px">code ${esc(g.code)}</div></div>`).join("");
}
function landToggleCreate() {
  const host = document.getElementById("lCreateRow");
  host.innerHTML = `<div class="row"><input id="grpName" placeholder="Group name" autofocus>
    <button class="btn sm" style="flex:0 0 auto" onclick="landCreate()">Create</button></div><div class="err" id="createErr"></div>`;
  const inp = host.querySelector("#grpName"); inp.focus();
  inp.addEventListener("keydown", e => { if (e.key === "Enter") landCreate(); });
}
function landToggleJoin() {
  const host = document.getElementById("lJoinRow");
  host.innerHTML = `<div class="row"><input id="joinCode" maxlength="6" placeholder="6-char code" style="text-transform:uppercase" autofocus>
    <button class="btn sm clay" style="flex:0 0 auto" onclick="landJoin()">Join</button></div>`;
  const inp = host.querySelector("#joinCode"); inp.focus();
  inp.addEventListener("keydown", e => { if (e.key === "Enter") landJoin(); });
}
async function landCreate() {
  const name = document.getElementById("grpName").value.trim(); const err = document.getElementById("createErr"); err.textContent = "";
  if (!name) { err.textContent = "name required"; return; }
  try {
    const g = await api("/api/group/create", { name }); LS.add(g);
    document.getElementById("landCreated").innerHTML = `<div class="card" style="border:2px solid var(--clay)">
      <div style="font-weight:800">✔ ${esc(g.name)} created</div>
      <div style="margin-top:4px">Share this code: <b style="font-size:16px;letter-spacing:2px">${esc(g.code)}</b></div>
      <button class="btn" style="margin-top:10px" onclick="location.href='/g/${g.code}/live'">Enter ▶</button></div>`;
    document.getElementById("lCreateRow").innerHTML = `<button class="btn ghost sm" onclick="landToggleCreate()">+ Create a group</button>`;
    renderMyGroups();
  } catch (e) { err.textContent = e; }
}
async function landJoin() {
  const code = document.getElementById("joinCode").value.trim().toUpperCase(); const err = document.getElementById("joinErr"); err.textContent = "";
  try { const g = await api("/api/group/join", { code }); LS.add(g); location.href = "/g/" + g.code + "/live"; }
  catch (e) { err.textContent = e; }
}
