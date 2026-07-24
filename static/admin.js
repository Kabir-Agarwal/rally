"use strict";
// Rally admin god-mode client. Key kept in localStorage, sent as X-Admin-Key.
// No popups — inline inputs + typed confirms only. Wrong/missing key => generic "not found".

const KEYLS = "rally_admin_key";
const getKey = () => localStorage.getItem(KEYLS) || "";
const el = (h) => { const d = document.createElement("div"); d.innerHTML = h.trim(); return d.firstChild; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const av = (n) => `<span class="avatar">${esc((n || "?")[0]).toUpperCase()}</span>`;

async function adminApi(url, body) {
  const opt = { method: body ? "POST" : "GET", headers: { "X-Admin-Key": getKey() } };
  if (body) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (r.status === 404) throw { notfound: true };        // wrong/missing key OR gone
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw (j.error || ("error " + r.status));
  return j;
}

function saveKey() {
  const k = document.getElementById("adminKey").value.trim();
  if (!k) return;
  localStorage.setItem(KEYLS, k);
  boot();
}
function lock(msg) {
  document.getElementById("adminBody").style.display = "none";
  document.getElementById("keyGate").style.display = "block";
  document.getElementById("keyErr").textContent = msg || "";
}

// ---- dashboard ----
async function boot() {
  let d;
  try { d = await adminApi("/admin/api/dashboard"); }
  catch (e) { lock(e && e.notfound ? "not found" : ""); return; }
  document.getElementById("keyGate").style.display = "none";
  document.getElementById("adminBody").style.display = "block";
  renderTotals(d.totals);
  renderGroups(d.groups);
  renderLog(d.log);
}
function renderTotals(t) {
  document.getElementById("totals").innerHTML =
    `<div class="row" style="text-align:center">
      ${[["Groups", t.groups], ["Players", t.players], ["Matches", t.matches], ["Live", t.live]]
        .map(([k, v]) => `<div class="setcol"><div style="font-size:22px;font-weight:900">${v}</div><div class="muted">${k}</div></div>`).join("")}
    </div>`;
}
function renderLog(log) {
  const host = document.getElementById("adminLog");
  if (!log.length) { host.innerHTML = `<div class="empty">No admin actions yet.</div>`; return; }
  host.innerHTML = log.map(r =>
    `<div class="lbrow" style="cursor:default"><div class="nm" style="font-size:12px">${esc(r.action)} <span class="muted">${esc(r.target || "")}</span></div>
      <div class="muted" style="font-size:11px">${esc((r.at || "").replace("T", " "))}</div></div>`).join("");
}
function renderGroups(groups) {
  const host = document.getElementById("groups"); host.innerHTML = "";
  if (!groups.length) { host.innerHTML = `<div class="empty">No groups.</div>`; return; }
  groups.forEach(g => host.appendChild(groupCard(g)));
}
function groupCard(g) {
  const card = el(`<div class="card" id="g${g.id}"></div>`);
  card.innerHTML = `
    <div class="row" style="align-items:flex-start">
      <div style="flex:1">
        <div style="font-weight:800">${g.live ? '<span class="dot pulse"></span>' : ''}${esc(g.name)}
          <span class="tag">${esc(g.code)}</span>
          <span class="pill ${g.is_public ? 'live' : ''}">${g.is_public ? 'PUBLIC' : 'PRIVATE'}</span></div>
        <div class="muted" style="font-size:12px">${g.players} players · ${g.matches} matches · created ${esc((g.created_at || '').slice(0, 10))}
          · last ${esc((g.last_activity || '—').replace('T', ' '))}</div>
      </div>
    </div>
    <div class="row" style="margin-top:8px;flex-wrap:wrap">
      <a class="btn sm ghost" style="text-align:center" href="/g/${g.code}/live">Open ▶</a>
      <button class="btn sm ghost" onclick="toggleDetail(${g.id},'${g.code}')">Manage</button>
    </div>
    <div id="detail${g.id}"></div>`;
  return card;
}

async function toggleDetail(gid, code) {
  const host = document.getElementById("detail" + gid);
  if (host.dataset.open) { host.innerHTML = ""; host.dataset.open = ""; return; }
  host.dataset.open = "1";
  let d;
  try { d = await adminApi(`/admin/api/group/${gid}`); }
  catch (e) { if (e && e.notfound) return lock("not found"); host.innerHTML = `<div class="err">${esc(e)}</div>`; return; }
  const g = d.group;
  host.innerHTML = "";
  // group controls
  const ctl = el(`<div style="border-top:1px solid var(--line);margin-top:10px;padding-top:10px"></div>`);
  ctl.appendChild(el(`<div class="row"><input id="rn${gid}" value="${esc(g.name)}"><button class="btn sm" onclick="grpRename(${gid})">Rename</button></div>`));
  ctl.appendChild(el(`<div class="row" style="margin-top:6px">
    <button class="btn sm ${g.is_public ? 'clay' : 'ghost'}" onclick="grpPublic(${gid},${g.is_public ? 'false' : 'true'})">${g.is_public ? 'Make private' : 'Make public'}</button>
    <button class="btn sm ghost" onclick="grpRegen(${gid})">Regenerate code</button></div>`));
  ctl.appendChild(danger(`Delete group — type "${g.name}"`, g.name, `del${gid}`,
    () => grpDelete(gid)));
  ctl.appendChild(el(`<div class="err" id="gerr${gid}"></div>`));
  host.appendChild(ctl);

  // players — admin is the ONLY place players are added
  host.appendChild(el(`<div style="font-weight:800;margin-top:12px">Players</div>`));
  const addBox = el(`<div><div class="row" style="margin-top:6px"><input id="newp${gid}" placeholder="+ New player name">
    <button class="btn sm" onclick="plAdd('${g.code}',${gid})">Add player</button></div><div class="err" id="addperr${gid}"></div></div>`);
  host.appendChild(addBox);
  if (!d.players.length) host.appendChild(el(`<div class="muted">none</div>`));
  d.players.forEach(p => {
    const box = el(`<div style="border:1px solid var(--line);border-radius:10px;padding:8px;margin-top:6px"></div>`);
    box.appendChild(el(`<div class="row"><input id="pn${p.id}" value="${esc(p.name)}"><button class="btn sm" onclick="plRename(${p.id})">Rename</button></div>`));
    box.appendChild(danger(`Delete ${p.name} + their matches — type "${p.name}"`, p.name, `pdel${p.id}`,
      () => plDelete(p.id)));
    box.appendChild(el(`<div class="err" id="perr${p.id}"></div>`));
    host.appendChild(box);
  });

  // matches
  host.appendChild(el(`<div style="font-weight:800;margin-top:12px">Matches</div>`));
  if (!d.matches.length) host.appendChild(el(`<div class="muted">none</div>`));
  d.matches.forEach(m => host.appendChild(matchAdmin(m)));
}

// typed-confirm helper: returns a node with an input + button that only fires on exact match
function danger(label, expected, id, fn) {
  const node = el(`<div style="margin-top:6px">
    <div class="muted" style="font-size:12px">${esc(label)}</div>
    <div class="row" style="margin-top:4px">
      <input id="${id}" placeholder="type to confirm">
      <button class="btn sm danger" onclick="__confirm('${id}')">Confirm</button>
    </div></div>`);
  window.__confirmFns = window.__confirmFns || {};
  window.__confirmFns[id] = { expected, fn };
  return node;
}
window.__confirm = function (id) {
  const rec = window.__confirmFns[id];
  const v = (document.getElementById(id).value || "").trim();
  if (v !== rec.expected) { document.getElementById(id).style.borderColor = "#c0392b"; return; }
  rec.fn();
};

function matchAdmin(m) {
  const box = el(`<div style="border:1px solid var(--line);border-radius:10px;padding:8px;margin-top:6px" id="m${m.id}"></div>`);
  let who = m.kind === "tt"
    ? m.rotation.map(r => esc(r.name)).join(" · ")
    : m.side1.map(p => esc(p.name)).join(" & ") + " vs " + m.side2.map(p => esc(p.name)).join(" & ");
  const statusPill = `<span class="pill ${m.status === 'live' ? 'live' : ''}">${m.status.replace('_', ' ')}</span>`;
  box.innerHTML = `<div style="font-weight:700;font-size:13px">${who} ${statusPill}</div>`;

  if (m.kind !== "tt") {
    const sets = m.sets.length ? m.sets : [{ g1: 0, g2: 0 }];
    let rows = sets.map((s, i) => `<div class="row" style="margin-top:4px">
      <input type="number" min="0" value="${s.g1}" id="ms${m.id}_${i}_1" style="text-align:center">
      <span style="flex:0 0 auto">–</span>
      <input type="number" min="0" value="${s.g2}" id="ms${m.id}_${i}_2" style="text-align:center"></div>`).join("");
    box.appendChild(el(`<div id="mrows${m.id}" data-n="${sets.length}">${rows}</div>`));
    box.appendChild(el(`<button class="btn sm ghost" style="width:auto;margin-top:4px" onclick="mAddSet(${m.id})">+ Add set</button>`));
  } else {
    box.appendChild(el(`<div class="muted" style="font-size:12px">${m.tally.map(t => esc(t.name) + ':' + t.wins).join(' · ')} (tt tally — edit date/kind only)</div>`));
  }
  box.appendChild(el(`<div class="row" style="margin-top:6px">
    <input type="date" id="md${m.id}" value="${esc(m.played_on || '')}">
    <select id="mk${m.id}">
      ${["singles", "doubles", "tt"].map(k => `<option value="${k}" ${k === m.kind ? 'selected' : ''}>${k}</option>`).join("")}
    </select>
    <button class="btn sm" onclick="mEdit(${m.id})">Save</button></div>`));

  // v2 admin actions: void/unvoid (exclude from ratings), restore (undo delete)
  if (m.voided) box.appendChild(el(`<div class="pill" style="margin-top:6px">VOIDED — excluded from ratings</div>`));
  if (m.deleted) box.appendChild(el(`<div class="pill" style="margin-top:6px;background:#f4d6d0;color:#7a1f16">DELETED</div>`));
  const acts = el(`<div class="row" style="margin-top:6px;flex-wrap:wrap"></div>`);
  if (!m.deleted) {
    acts.appendChild(m.voided
      ? el(`<button class="btn sm clay" style="width:auto" onclick="mUnvoid(${m.id})">Unvoid</button>`)
      : el(`<button class="btn sm ghost" style="width:auto" onclick="mVoid(${m.id})">Void</button>`));
  }
  if (m.deleted)
    acts.appendChild(el(`<button class="btn sm clay" style="width:auto" onclick="mRestore(${m.id})">Restore</button>`));
  box.appendChild(acts);
  if (!m.deleted)
    box.appendChild(danger(`Delete this match — type "delete"`, "delete", `mdel${m.id}`, () => mDelete(m.id)));
  box.appendChild(el(`<div class="err" id="merr${m.id}"></div>`));
  return box;
}

// ---- actions ----
async function guard(fn, errId) {
  try { await fn(); await boot(); }
  catch (e) {
    if (e && e.notfound) return lock("not found");
    if (errId) { const n = document.getElementById(errId); if (n) n.textContent = e; }
  }
}
async function adminCreateGroup() {
  const name = document.getElementById("newGroupName").value.trim();
  if (!name) return;
  await guard(() => adminApi("/admin/api/group/create", { name }), "createErr");
}
const grpRename = (gid) => guard(() => adminApi(`/admin/api/group/${gid}/rename`, { name: document.getElementById("rn" + gid).value }), "gerr" + gid);
const grpPublic = (gid, val) => guard(() => adminApi(`/admin/api/group/${gid}/public`, { is_public: val }), "gerr" + gid);
const grpRegen = (gid) => guard(() => adminApi(`/admin/api/group/${gid}/regen`, {}), "gerr" + gid);
const grpDelete = (gid) => guard(() => adminApi(`/admin/api/group/${gid}/delete`, { confirm: document.getElementById("del" + gid).value }), "gerr" + gid);
async function plAdd(code, gid) {
  const inp = document.getElementById("newp" + gid); const name = inp.value.trim();
  if (!name) return;
  try {
    const r = await fetch(`/g/${code}/api/player`, { method: "POST", headers: { "Content-Type": "application/json", "X-Admin-Key": getKey() }, body: JSON.stringify({ name }) });
    if (r.status === 404) return lock("not found");
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { document.getElementById("addperr" + gid).textContent = j.error || "error"; return; }
    inp.value = ""; toggleDetail(gid, code); toggleDetail(gid, code);   // refresh detail
  } catch (e) { document.getElementById("addperr" + gid).textContent = e; }
}
const plRename = (pid) => guard(() => adminApi(`/admin/api/player/${pid}/rename`, { name: document.getElementById("pn" + pid).value }), "perr" + pid);
const plDelete = (pid) => guard(() => adminApi(`/admin/api/player/${pid}/delete`, { confirm: document.getElementById("pdel" + pid).value }), "perr" + pid);

function mAddSet(id) {
  const rows = document.getElementById("mrows" + id); const n = +rows.dataset.n; if (n >= 5) return;
  rows.appendChild(el(`<div class="row" style="margin-top:4px"><input type="number" min="0" value="0" id="ms${id}_${n}_1" style="text-align:center"><span style="flex:0 0 auto">–</span><input type="number" min="0" value="0" id="ms${id}_${n}_2" style="text-align:center"></div>`));
  rows.dataset.n = n + 1;
}
function mEdit(id) {
  const body = { played_on: document.getElementById("md" + id).value || null, kind: document.getElementById("mk" + id).value };
  const rows = document.getElementById("mrows" + id);
  if (rows) {
    const n = +rows.dataset.n; const sets = [];
    for (let i = 0; i < n; i++) sets.push([+document.getElementById(`ms${id}_${i}_1`).value || 0, +document.getElementById(`ms${id}_${i}_2`).value || 0]);
    body.sets = sets;
  }
  guard(() => adminApi(`/admin/api/match/${id}/edit`, body), "merr" + id);
}
const mDelete = (id) => guard(() => adminApi(`/admin/api/match/${id}/delete`, {}), "merr" + id);
const mVoid = (id) => guard(() => adminApi(`/admin/api/match/${id}/void`, {}), "merr" + id);
const mUnvoid = (id) => guard(() => adminApi(`/admin/api/match/${id}/unvoid`, {}), "merr" + id);
const mRestore = (id) => guard(() => adminApi(`/admin/api/match/${id}/restore`, {}), "merr" + id);

document.addEventListener("DOMContentLoaded", () => { if (getKey()) boot(); });
