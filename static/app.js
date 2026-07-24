"use strict";
/* Rally v2 client. No popups anywhere. Auth-gated writes; instant DOM from the client engine
   (engine.js) with background sync (sync.js); poll for read views; 0-based rating display. */

// ---------- helpers ----------
const el = (h) => { const d = document.createElement("div"); d.innerHTML = h.trim(); return d.firstChild; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const av = (n) => `<span class="avatar">${esc((n || "?")[0]).toUpperCase()}</span>`;
const authHeaders = () => (window.Auth ? Auth.headers() : {});

async function api(url, body, method) {
  const m = method || (body ? "POST" : "GET");
  const opt = { method: m, headers: { ...authHeaders() } };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw (j.error || ("error " + r.status));
  return j;
}

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

// ---------- auth gate + identity ----------
async function authGate() {
  // Every tab needs a signed-in identity to act. Public reads still work, but the app is
  // gated to sign-in first (the reference UI signs in before the group tabs).
  if (window.Auth && Auth.signedIn()) return true;
  const tc = document.getElementById("tabContent");
  if (tc) tc.style.display = "none";
  const gate = el(`<div id="signinGate"></div>`);
  document.querySelector(".app").appendChild(gate);
  Auth.renderSignIn(gate, () => location.reload());
  return false;
}

async function ensureIdentity() {
  ME = await api(`/g/${GROUP.code}/api/me`);
  if (ME.signed_in && !ME.player_id) return await pickWhoAmI();
  return true;
}
async function pickWhoAmI() {
  const meta = await api(`/g/${GROUP.code}/api/meta`);
  return new Promise((resolve) => {
    const ov = el(`<div class="modal" id="whoModal"><div class="sheet3">
      <div style="font-weight:800;font-size:17px">Which player are you?</div>
      <div class="muted" style="margin:2px 0 10px">Pick once — this locks to your account. Players are added by the admin.</div>
      <div class="chips" id="whoChips"></div>
      <div class="err" id="whoErr"></div></div></div>`);
    document.body.appendChild(ov);
    const chips = ov.querySelector("#whoChips");
    if (!meta.players.length) chips.innerHTML = '<span class="muted">No players yet — ask the admin to add players.</span>';
    meta.players.forEach(p => {
      const chip = el(`<div class="chip">${esc(p.name)}</div>`);
      chip.onclick = async () => {
        try {
          await api(`/g/${GROUP.code}/api/link`, { player_id: p.id });
          ME = await api(`/g/${GROUP.code}/api/me`);
          ov.remove(); resolve(true);
        } catch (e) { ov.querySelector("#whoErr").textContent = e; }
      };
      chips.appendChild(chip);
    });
  });
}

// ---------- header switcher ----------
async function openSwitcher() {
  const s = document.getElementById("switcher"); if (!s) return; s.classList.add("open");
  const list = document.getElementById("switcherList"); const gs = LS.groups();
  list.innerHTML = gs.length ? "" : '<div class="muted">No other groups yet.</div>';
  gs.forEach(async g => {
    const cur = g.code === GROUP.code;
    const row = el(`<div class="grp"><span class="gname">${esc(g.name)}${cur ? ' <span class="tickmark">✓</span>' : ''}</span>
      <span class="tag">${g.code}</span><span class="dw"></span></div>`);
    row.onclick = () => { if (!cur) location.href = "/g/" + g.code + "/live"; };
    list.appendChild(row);
    try { const d = await api(`/g/${g.code}/api/live`); if (d.matches.length) row.querySelector(".dw").innerHTML = '<span class="dot pulse"></span>'; } catch (e) { }
  });
}
function closeSwitcher() { const s = document.getElementById("switcher"); if (s) s.classList.remove("open"); }

// ---------- polling ----------
function poll(fn, ms) { fn(); return setInterval(() => { if (!document.hidden) fn(); }, ms || 3000); }

// ---------- rating display (0-based) ----------
const disp = (elo0based) => (elo0based > 0 ? "+" : "") + elo0based;   // meta already 0-based
const dispFromElo = (elo) => { const v = Math.round(elo) - 1200; return (v > 0 ? "+" : "") + v; };

// ---------- shared: broadcast/scoreboard card (read-only) ----------
function winBar(wp, kind) {
  if (!wp || !wp.length) return "";
  if (kind === "tt") {
    return `<div class="wp3">` + wp.map(w =>
      `<div class="wp3seg"><div class="wp3name">${esc(w.label)}</div><div class="wp3pct">${w.pct}%</div></div>`).join("") + `</div>`;
  }
  const a = wp[0], b = wp[1];
  return `<div class="wp2"><span class="wpend">${esc(a.label)} · ${a.pct}%</span>
    <span class="wpbar"><span class="wpfill" style="width:${a.pct}%"></span></span>
    <span class="wpend right">${b.pct}% · ${esc(b.label)}</span></div>`;
}

function broadcastCard(m) {
  const started = (m.played_on || "");
  if (m.kind === "tt") {
    const p = m.pairing;
    let head = `<div class="bhead">TRIPLE THREAT · LIVE</div>`;
    let strip = `<div class="ttstrip">` + m.tally.map(t => `<div class="ttcell">${esc(t.name)} <b>${t.wins}</b></div>`).join("") + `</div>`;
    let line = p ? `<div class="server">Server 🎾 ${esc(p.server)} · ${esc(p.receiver)} Receiver</div>
      <div class="muted">Game ${m.game_no + 1} · ${esc(p.sitter)} sits out</div>` : "";
    return el(`<div class="bcast">${head}${strip}${line}${winBar(m.win_prob, "tt")}${m.group ? `<div class="note">${esc(m.group)}</div>` : ""}</div>`);
  }
  const w1 = m.winner_side === 1, w2 = m.winner_side === 2;
  const side = (arr, srvId) => arr.map(p => `<div class="bname">${p.id === m.server_id ? '🎾 ' : ''}${esc(p.name)}</div>`).join("");
  let cols = m.sets.map(s => `<div class="setcol"><div class="setcell ${s.won1 ? 'won' : ''}">${s.g1}</div><div class="setcell ${s.won2 ? 'won' : ''}">${s.g2}</div></div>`).join("");
  let pts = (m.per_point && m.point_score) ? `<div class="ptsbox">${esc(m.point_score)}</div>` : "";
  return el(`<div class="bcast">
    <div class="bhead">${m.kind.toUpperCase()} · LIVE</div>
    <div class="brow"><div class="bteam">${side(m.side1)}</div><div class="bsets">${cols}</div>${pts}</div>
    <div class="brow"><div class="bteam">${side(m.side2)}</div></div>
    ${winBar(m.win_prob, m.kind)}${m.group ? `<div class="note">${esc(m.group)}</div>` : ""}</div>`);
}

// ================= LIVE =================
function initLive() {
  poll(async () => {
    const d = await api(`/g/${GROUP.code}/api/live`);
    const host = document.getElementById("liveMatches"); host.innerHTML = "";
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
  RANK.data = await api(`/g/${GROUP.code}/api/leaderboard?scope=${RANK.scope}&mode=${RANK.mode}`);
  renderRanks();
}
function rankRow(r, mePid) {
  const you = r.id == mePid && RANK.scope === "group";
  const dot = r.live ? '<span class="dot pulse"></span>' : '<span class="dotspace"></span>';
  const tag = r.group ? `<span class="tag">${esc(r.group)}</span>` : "";
  const rating = dispFromEloRow(r);
  return `<div class="lbrow ${you ? 'you' : ''}" onclick="location.href='/g/${GROUP.code}/player/${r.id}'">
    <div class="rk">${r.rank || '–'}</div>${av(r.name)}
    <div class="nm">${dot}${esc(r.name)}${tag}${you ? ' <span class="youpill">YOU</span>' : ''}<div class="tapstats">tap for stats</div></div>
    <div class="rt">${rating}</div></div>`;
}
const dispFromEloRow = (r) => { const v = r.rating - 1200; return (v > 0 ? "+" : "") + v; };
function renderRanks() {
  if (!RANK.data) return;
  const q = (document.getElementById("rankSearch").value || "").toLowerCase();
  const filt = a => a.filter(r => r.name.toLowerCase().includes(q));
  const ranked = filt(RANK.data.ranked), prov = filt(RANK.data.provisional);
  const yc = document.getElementById("youCard"); yc.innerHTML = "";
  if (ME.player_id && RANK.scope === "group") {
    const you = RANK.data.ranked.find(r => r.id == ME.player_id);
    if (you) yc.appendChild(el(`<div class="youcard" onclick="location.href='/g/${GROUP.code}/player/${you.id}'">${av(you.name)}
      <div style="flex:1"><b>${esc(you.name)}</b> <span class="youpill">YOU</span></div>
      <div>#${you.rank} · <b>${dispFromEloRow(you)}</b></div></div>`));
  }
  document.getElementById("rankList").innerHTML = ranked.length ? ranked.map(r => rankRow(r, ME.player_id)).join("") : `<div class="empty">No ranked players yet.</div>`;
  const provWrap = document.getElementById("provWrap");
  provWrap.innerHTML = prov.length
    ? `<div class="sec-title">Minimum 5 matches</div><div class="card" style="padding:2px 2px">` +
      prov.map(r => `<div class="lbrow" onclick="location.href='/g/${GROUP.code}/player/${r.id}'"><div class="rk">–</div>${av(r.name)}
        <div class="nm">${r.live ? '<span class="dot pulse"></span>' : '<span class="dotspace"></span>'}${esc(r.name)}${r.group ? `<span class="tag">${esc(r.group)}</span>` : ''}</div>
        <div class="rt">${dispFromEloRow(r)} <span class="pill">${r.n} of 5</span></div></div>`).join("") + `</div>`
    : "";
}
function initRanks() { loadRanks(); poll(async () => { await loadRanks(); }, 5000); }

// ================= GROUPS =================
async function initGroups() {
  const acc = document.getElementById("accountCard");
  acc.innerHTML = `<div class="row"><div style="flex:1"><div style="font-weight:800">${esc(ME.email || "Signed in")}</div>
    <div class="muted">You are <b>${esc(ME.player_name || "— pick in a moment")}</b> in ${esc(GROUP.name)}</div></div>
    <button class="btn sm ghost" onclick="Auth.signOut();location.reload()">Sign out</button></div>`;
  renderGroupRows();
}
function renderGroupRows() {
  const host = document.getElementById("groupRows"); const gs = LS.groups(); host.innerHTML = "";
  gs.forEach(async g => {
    const cur = g.code === GROUP.code;
    const row = el(`<div class="grouprow ${cur ? 'cur' : ''}">
      <div style="flex:1"><b>${esc(g.name)}</b> <span class="tag">${g.code}</span> <span class="dw"></span></div>
      <button class="btn sm ${g.is_public ? 'clay' : 'ghost'}" onclick="event.stopPropagation();flipPublic('${g.code}',this)">${g.is_public ? 'Public' : 'Private'}</button>
      ${cur ? '<span class="tickmark">✓</span>' : ''}</div>`);
    row.onclick = () => { if (!cur) location.href = "/g/" + g.code + "/live"; };
    host.appendChild(row);
    try { const d = await api(`/g/${g.code}/api/live`); if (d.matches.length) row.querySelector(".dw").innerHTML = '<span class="dot pulse"></span>'; } catch (e) { }
  });
  if (!gs.length) host.innerHTML = '<div class="empty">No groups yet.</div>';
}
async function flipPublic(code, btn) {
  const g = LS.groups().find(x => x.code === code); const next = !(g && g.is_public);
  try {
    await api(`/g/${code}/api/public`, { is_public: next });
    if (g) { g.is_public = next; LS.add(g); }
    if (code === GROUP.code) GROUP.is_public = next;
    btn.className = "btn sm " + (next ? "clay" : "ghost"); btn.textContent = next ? "Public" : "Private";
  } catch (e) { }
}
async function createGroup() {
  const name = document.getElementById("newGroupName").value.trim(); const out = document.getElementById("createOut");
  if (!name) { out.textContent = "name required"; return; }
  try {
    const g = await api("/api/group/create", { name }); LS.add(g);
    out.innerHTML = `Created <b>${g.code}</b> — <a href="/g/${g.code}/live">enter ▶</a>`;
    document.getElementById("codeShare").textContent = g.code; document.getElementById("codeShareBox").style.display = "block";
    renderGroupRows();
  } catch (e) { out.textContent = e; }
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
  const d = await api(`/g/${GROUP.code}/api/history`);
  const host = document.getElementById("historyList"); host.innerHTML = "";
  let matches = d.matches;
  if (HIST.kind !== "all") matches = matches.filter(m => m.kind === HIST.kind);
  if (!matches.length) { host.innerHTML = `<div class="empty">No finished matches.</div>`; return; }
  matches.forEach(m => host.appendChild(historyCard(m)));
}
function historyCard(m) {
  const when = esc((m.played_on || "").replace("T", " "));
  let title;
  if (m.kind === "tt") title = m.rotation.map(r => esc(r.name)).join(" · ");
  else {
    const w1 = m.winner_side === 1, w2 = m.winner_side === 2;
    title = `<span class="${w1 ? 'winr' : ''}">${m.side1.map(p => esc(p.name)).join(" & ")}${w1 ? ' 🏆' : ''}</span> vs
             <span class="${w2 ? 'winr' : ''}">${m.side2.map(p => esc(p.name)).join(" & ")}${w2 ? ' 🏆' : ''}</span>`;
  }
  let sets = m.kind === "tt"
    ? `<div class="ttstrip">${m.tally.map(t => `<div class="ttcell">${esc(t.name)} <b>${t.wins}</b></div>`).join("")}</div>`
    : `<div class="sheet">${m.sets.map(s => `<div class="setcol"><div class="setcell ${s.won1 ? 'won' : ''}">${s.g1}</div><div class="setcell ${s.won2 ? 'won' : ''}">${s.g2}</div></div>`).join("")}</div>`;
  const story = m.story ? storyLine(m.story) : "";
  const card = el(`<div class="match">
    <div class="names"><div class="side">${title}</div></div>${sets}
    <div class="note">${m.kind.toUpperCase()} · <span class="whenlbl">${when}</span>
      <button class="editdt" title="edit date/time">✎</button></div>
    <div class="dtedit" style="display:none"><input type="datetime-local" class="dtin">
      <button class="btn sm" >Save</button></div>${story}</div>`);
  const editBtn = card.querySelector(".editdt");
  editBtn.onclick = () => { const e = card.querySelector(".dtedit"); e.style.display = e.style.display === "flex" ? "none" : "flex"; e.style.gap = "6px"; e.querySelector(".dtin").value = toLocalInput(m.played_on); };
  card.querySelector(".dtedit .btn").onclick = async () => {
    const v = card.querySelector(".dtin").value; if (!v) return;
    try {
      await api(`/g/${GROUP.code}/api/match/${m.id}/date`, { played_on: v.replace("T", " ") });
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

// ================= PLAYER =================
function initPlayer() {
  const host = document.getElementById("pmHist"); if (!host) return;
  if (ME.player_id == PLAYER.id) { const b = document.getElementById("youBadge"); if (b) b.innerHTML = '<span class="youpill">YOU</span>'; }
  if (!PLAYER.matches.length) { host.innerHTML = '<div class="empty">No matches yet.</div>'; return; }
  host.innerHTML = "";
  PLAYER.matches.forEach(m => host.appendChild(historyCardStatic(m)));
}
function historyCardStatic(m) {
  const when = esc((m.played_on || "").replace("T", " "));
  let title, sets;
  if (m.kind === "tt") { title = m.rotation.map(r => esc(r.name)).join(" · "); sets = `<div class="ttstrip">${m.tally.map(t => `<div class="ttcell">${esc(t.name)} <b>${t.wins}</b></div>`).join("")}</div>`; }
  else {
    const w1 = m.winner_side === 1, w2 = m.winner_side === 2;
    title = `${m.side1.map(p => esc(p.name)).join(" & ")}${w1 ? ' 🏆' : ''} vs ${m.side2.map(p => esc(p.name)).join(" & ")}${w2 ? ' 🏆' : ''}`;
    sets = `<div class="sheet">${m.sets.map(s => `<div class="setcol"><div class="setcell ${s.won1 ? 'won' : ''}">${s.g1}</div><div class="setcell ${s.won2 ? 'won' : ''}">${s.g2}</div></div>`).join("")}</div>`;
  }
  return el(`<div class="match"><div class="names"><div class="side">${title}</div></div>${sets}<div class="note">${m.kind.toUpperCase()} · ${when}</div></div>`);
}

// ---------- boot ----------
document.addEventListener("DOMContentLoaded", async () => {
  const page = window.PAGE;
  if (page === "landing") { return initLanding(); }
  if (!GROUP) return;
  if (!(await authGate())) return;         // shows sign-in, reloads on success
  try { await ensureIdentity(); } catch (e) { }
  if (page === "live") initLive();
  else if (page === "leaderboard") initRanks();
  else if (page === "log") initLog();
  else if (page === "groups") initGroups();
  else if (page === "history") initHistory();
  else if (page === "player") initPlayer();
});

// ---------- landing ----------
function initLanding() {
  const host = document.getElementById("landingContent");
  if (window.Auth && !Auth.signedIn()) { Auth.renderSignIn(host, () => location.reload()); return; }
  host.innerHTML = `
    <div id="myGroups"></div>
    <div class="card"><div style="font-weight:800;margin-bottom:8px">Join a group</div>
      <div class="row"><input id="joinCode" maxlength="6" placeholder="6-char code" style="text-transform:uppercase">
      <button class="btn sm clay" onclick="landJoin()">Join</button></div><div class="err" id="joinErr"></div></div>
    <div class="card"><div style="font-weight:800;margin-bottom:8px">Create a group</div>
      <div class="row"><input id="grpName" placeholder="group name"><button class="btn sm" onclick="landCreate()">Create</button></div>
      <div class="err" id="createErr"></div><div id="createDone" style="display:none">
      <div class="muted">Share this code:</div><div class="bignum" id="newCode"></div>
      <button class="btn" style="margin-top:10px" id="enterBtn">Enter ▶</button></div></div>
    <div class="card" style="text-align:center"><span class="muted">${esc(Auth.email())}</span> · <a href="#" onclick="Auth.signOut();location.reload();return false">sign out</a></div>`;
  renderMyGroups();
}
function renderMyGroups() {
  const host = document.getElementById("myGroups"); if (!host) return;
  const gs = LS.groups(); if (!gs.length) { host.innerHTML = ""; return; }
  host.innerHTML = `<div class="sec-title">Your groups</div>`;
  const card = el(`<div class="card" style="padding:4px 4px"></div>`);
  gs.forEach(g => card.appendChild(el(`<div class="lbrow" onclick="location.href='/g/${g.code}/live'"><div class="nm">${esc(g.name)}</div><div class="tag">${g.code}</div></div>`)));
  host.appendChild(card);
}
async function landCreate() {
  const name = document.getElementById("grpName").value.trim(); const err = document.getElementById("createErr"); err.textContent = "";
  if (!name) { err.textContent = "name required"; return; }
  try {
    const g = await api("/api/group/create", { name }); LS.add(g);
    document.getElementById("createDone").style.display = "block";
    document.getElementById("newCode").textContent = g.code;
    document.getElementById("enterBtn").onclick = () => location.href = "/g/" + g.code + "/live";
  } catch (e) { err.textContent = e; }
}
async function landJoin() {
  const code = document.getElementById("joinCode").value.trim().toUpperCase(); const err = document.getElementById("joinErr"); err.textContent = "";
  try { const g = await api("/api/group/join", { code }); LS.add(g); location.href = "/g/" + g.code + "/live"; }
  catch (e) { err.textContent = e; }
}
