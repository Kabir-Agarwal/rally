"use strict";
/* Rally Log tab (Task 6c): court picker, chemistry, start rules, live editor (engine + sync),
   TT confirm-rotation, already-played. Loaded only on the Log page (needs app.js + engine.js). */

let PLAYERS = [], PAIRS = {}, PAIRPROV = 3;
let NEW = { kind: "singles", slots: [], firstServe: null };
let EDIT = null;   // live editor state

function slotDefs(kind) {
  if (kind === "singles") return [{ label: "Serves 🎾", cls: "near" }, { label: "Receives", cls: "far" }];
  if (kind === "doubles") return [
    { label: "Team 1 · deuce", cls: "near" }, { label: "Team 1 · ad", cls: "near" },
    { label: "Team 2 · deuce", cls: "far" }, { label: "Team 2 · ad", cls: "far" }];
  return [{ label: "Serves 🎾", cls: "near" }, { label: "Receives", cls: "far" }, { label: "Sits out", cls: "bench" }];
}
function needSlots(kind) { return kind === "singles" ? 2 : kind === "doubles" ? 4 : 3; }

let LOG_BUILT = false;
async function initLog(isRefresh) {
  await refreshMeta();
  if (LOG_BUILT && isRefresh) {          // tab re-entry: refresh without wiping picker/editor state
    renderCourt(); loadEditor(); poll(loadEditor, 4000);
    return;
  }
  LOG_BUILT = true;
  document.getElementById("logRoot").innerHTML =
    '<div class="sec-title">Start a live match</div>' +
    '<div class="card">' +
    '  <div class="seg" id="kindSeg">' +
    '    <button class="on" onclick="setKind(\'singles\',this)">Singles</button>' +
    '    <button onclick="setKind(\'doubles\',this)">Doubles</button>' +
    '    <button onclick="setKind(\'tt\',this)">Triple threat</button></div>' +
    '  <div id="courtWrap"></div><div id="chemRows"></div>' +
    '  <div class="err" id="startErr"></div><div id="startMsg" class="note"></div>' +
    '  <button class="btn" id="startBtn" style="margin-top:8px" onclick="startMatch()">▶ Start</button></div>' +
    '<div class="sec-title">Update the live match</div>' +
    '<div id="liveEditor"><div class="empty">No live match yet.</div></div>' +
    '<div class="sec-title">Already played? Final score</div>' +
    '<div class="card" id="playedCard"></div>';
  setKind(NEW.kind);
  buildPlayed();
  loadEditor();
  poll(loadEditor, 4000);   // tracked poller — cleared when leaving the Log tab
}
async function refreshMeta() {
  const meta = await api(`/g/${GROUP.code}/api/meta`);
  PLAYERS = meta.players; PAIRS = meta.pairs; PAIRPROV = meta.pair_provisional;
}
function setKind(kind, btn) {
  NEW = { kind, slots: new Array(needSlots(kind)).fill(null), firstServe: null };
  if (btn) { document.querySelectorAll("#kindSeg button").forEach(b => b.classList.remove("on")); btn.classList.add("on"); }
  renderCourt();
}
function renderCourt() {
  const defs = slotDefs(NEW.kind);
  const pOf = id => PLAYERS.find(p => p.id === id) || { name: "" };
  const slotsHtml = defs.map((d, i) => {
    const pid = NEW.slots[i];
    const serves = (NEW.kind !== "tt" && NEW.firstServe === pid && pid) || (NEW.kind === "tt" && i === 0 && pid);
    const filled = pid ? (serves ? '🎾 ' : '') + pBlock(pOf(pid)) : '<span class="muted">tap a player</span>';
    return `<div class="cslot ${d.cls} ${pid ? 'filled' : ''}" onclick="slotTap(${i})">
      <div class="cslotlab">${d.label}</div>
      <div class="cslotname">${filled}</div></div>`;
  }).join("");
  const placed = NEW.slots.filter(Boolean);
  const roster = PLAYERS.map(p => {
    const sel = placed.includes(p.id);
    const live = p.live ? '<span class="dot pulse"></span>' : '';
    const real = p.real_name ? `<span class="chip-real">${esc(p.real_name)}</span>` : '';
    const busyNote = (p.live && !sel) ? '<span class="chip-real">· in a live match</span>' : '';
    return `<div class="chip ${sel ? 'sel' : ''} ${p.live && !sel ? 'busy' : ''}" onclick="rosterTap(${p.id})">${live}${esc(p.name)}${real}${busyNote}</div>`;
  }).join("");
  document.getElementById("courtWrap").innerHTML =
    `<div class="chips" style="margin-top:6px">${roster || '<span class="muted">No players yet — sign in and set up your player.</span>'}</div>
     <div class="court ${NEW.kind}"><div class="net"></div>${slotsHtml}</div>
     <div class="muted" style="margin-top:8px">Tap a chip to place · tap a placed player for first serve 🎾</div>`;
  renderChem(); updateStartBtn();
}
function rosterTap(pid) {
  const idx = NEW.slots.indexOf(pid);
  if (idx >= 0) { NEW.slots[idx] = null; if (NEW.firstServe === pid) NEW.firstServe = null; renderCourt(); return; }
  const p = PLAYERS.find(x => x.id === pid);
  if (p && p.live) {                    // Task 6: can't pick a player already in a live match
    const e = document.getElementById("startErr");
    if (e) e.textContent = esc(p.name) + " is already in a live match — finish it first.";
    return;
  }
  const empty = NEW.slots.indexOf(null);
  if (empty >= 0) { NEW.slots[empty] = pid; if (NEW.firstServe == null) NEW.firstServe = pid; }
  renderCourt();
}
function slotTap(i) {
  const pid = NEW.slots[i]; if (!pid || NEW.kind === "tt") return;   // TT: first-placed serves (fixed)
  NEW.firstServe = pid; renderCourt();
}
function renderChem() {
  const host = document.getElementById("chemRows"); if (!host) return;
  if (NEW.kind !== "doubles") { host.innerHTML = ""; return; }
  const teams = [[NEW.slots[0], NEW.slots[1]], [NEW.slots[2], NEW.slots[3]]];
  host.innerHTML = teams.map((t, n) => {
    if (!t[0] || !t[1]) return "";
    const key = [Math.min(t[0], t[1]), Math.max(t[0], t[1])].join("_");
    const pr = PAIRS[key];
    if (!pr || pr.n < PAIRPROV) {
      const need = PAIRPROV - (pr ? pr.n : 0);
      return `<div class="chemrow"><b>TEAM ${n + 1}</b> · Chemistry · <span class="muted">Unexplored — ${need} more match${need === 1 ? '' : 'es'} needed</span></div>`;
    }
    const sign = pr.rating >= 0 ? "pos" : "neg";
    return `<div class="chemrow"><b>TEAM ${n + 1}</b> · Chemistry · <span class="chem ${sign}">${pr.rating >= 0 ? '+' : ''}${pr.rating}</span></div>`;
  }).join("");
}
function anyLiveInGroup() { return PLAYERS.some(p => p.live); }
function updateStartBtn() {
  const btn = document.getElementById("startBtn"); if (!btn) return;
  if (EDIT && EDIT.mid) { btn.disabled = true; btn.textContent = "A match is already live"; btn.classList.add("greyed"); }
  else { btn.disabled = false; btn.textContent = "▶ Start"; btn.classList.remove("greyed"); }
}
function startPayload() {
  const s = NEW.slots;
  if (NEW.kind === "singles") { let a = s[0], b = s[1]; if (NEW.firstServe === b) { a = s[1]; b = s[0]; } return { kind: "singles", side1: [a], side2: [b] }; }
  if (NEW.kind === "doubles") {
    let t1 = [s[0], s[1]], t2 = [s[2], s[3]];
    if (NEW.firstServe && t2.includes(NEW.firstServe)) { const tmp = t1; t1 = t2; t2 = tmp; }
    if (NEW.firstServe && t1[1] === NEW.firstServe) t1 = [t1[1], t1[0]];
    return { kind: "doubles", side1: t1, side2: t2 };
  }
  return { kind: "tt", rotation: [s[0], s[1], s[2]] };
}
async function startMatch() {
  const err = document.getElementById("startErr"); err.textContent = "";
  if (NEW.slots.some(x => !x)) { err.textContent = "fill every slot"; return; }
  const busy = NEW.slots.filter(id => (PLAYERS.find(p => p.id === id) || {}).live);
  if (busy.length) { err.textContent = (PLAYERS.find(p => p.id === busy[0]).name) + " is already in a live match"; return; }
  if (anyLiveInGroup() || (EDIT && EDIT.mid)) { err.textContent = "A match is already live — finish it first"; return; }
  try {
    await api(`/g/${GROUP.code}/api/match/start`, startPayload());
    document.getElementById("startMsg").innerHTML = '✔ Match started — score it in <b>Update the live match</b> just below';
    setKind(NEW.kind); await refreshMeta(); renderCourt(); loadEditor();
  } catch (e) { err.textContent = e; }
}

// ---- live editor ----
async function loadEditor() {
  const d = await api(`/g/${GROUP.code}/api/live`);
  const m = d.matches[0];
  const host = document.getElementById("liveEditor");
  if (!m) { EDIT = null; if (host) host.innerHTML = `<div class="empty">No live match yet.</div>`; updateStartBtn(); return; }
  if (EDIT && EDIT.mid === m.id) { updateStartBtn(); return; }
  hydrateEditor(m); updateStartBtn();
}
function hydrateEditor(m) {
  if (m.kind === "tt") {
    const rot = m.rotation.map(r => r.id);
    EDIT = { mid: m.id, kind: "tt", rot, names: {}, game: null, cur: null, gameNo: (m.tt_games || []).length };
    m.rotation.forEach(r => EDIT.names[r.id] = r.name);
    const g = (m.tt_games || []);
    if (g.length && g[g.length - 1].server) {
      const last = g[g.length - 1];
      const sit = rot.find(x => x !== last.server && x !== last.receiver);
      EDIT.cur = { server: last.receiver, receiver: sit, sitter: last.server };
    } else EDIT.cur = { server: rot[0], receiver: rot[1], sitter: rot[2] };
    EDIT.game = new Engine.PointMatch("singles", [EDIT.cur.server, EDIT.cur.receiver]);
    renderTTEditor();
  } else {
    const order = m.kind === "singles" ? [m.side1[0].id, m.side2[0].id]
      : [m.side1[0].id, m.side2[0].id, m.side1[1].id, m.side2[1].id];
    const eng = new Engine.PointMatch(m.kind, order);
    (m.points || []).forEach(w => eng.addPoint(w));
    EDIT = { mid: m.id, kind: m.kind, eng, side1: m.side1, side2: m.side2, names: {} };
    [...m.side1, ...m.side2].forEach(p => EDIT.names[p.id] = p.name);
    renderPointEditor();
  }
}
function renderPointEditor() {
  const host = document.getElementById("liveEditor"); const m = EDIT; const s = m.eng.snapshot();
  const n1 = m.side1.map(p => esc(p.name)).join(" & "), n2 = m.side2.map(p => esc(p.name)).join(" & ");
  const serverName = s.server != null ? esc(m.names[s.server]) : "";
  const setsHtml = s.sets.concat([s.curGames]).map(g => `<div class="setcol"><div class="setcell">${g[0]}</div><div class="setcell">${g[1]}</div></div>`).join("");
  host.innerHTML = `<div class="card" id="ed${m.mid}">
    <div class="edhead">${n1} <span class="muted">vs</span> ${n2} <span class="syncchip synced" id="syncChip">● synced</span></div>
    <div class="bigscore">${esc(s.pointLabel)}</div>
    <div class="server">🎾 ${serverName} serving${s.isTiebreak ? ' · tiebreak' : ''}</div>
    <div class="sheet" style="justify-content:center;margin-top:6px">${setsHtml}</div>
    <div class="row" style="margin-top:10px"><button class="btn clay" onclick="pt(1)">Point ${n1}</button>
      <button class="btn clay" onclick="pt(2)">Point ${n2}</button></div>
    <button class="btn ghost sm" style="margin-top:8px;width:auto" onclick="ptUndo()">↶ Undo</button>
    <div class="row" style="margin-top:10px"><button class="btn ghost sm" onclick="toggleGrid()">Set scores</button>
      <button class="btn sm" onclick="finishMatch()">Mark finished</button>
      <button class="btn danger sm" onclick="deleteMatch()">Delete</button></div>
    <div id="gridBox"></div><div class="err" id="edErr"></div></div>`;
}
function pt(side) { EDIT.eng.addPoint(side); renderPointEditor(); enqueue(`/g/${GROUP.code}/api/match/${EDIT.mid}/point`, { winner_side: side }); }
function ptUndo() { EDIT.eng.undo(); renderPointEditor(); enqueue(`/g/${GROUP.code}/api/match/${EDIT.mid}/point/undo`, {}); }
function toggleGrid() {
  const box = document.getElementById("gridBox");
  if (box.dataset.open) { box.dataset.open = ""; box.innerHTML = ""; return; }
  box.dataset.open = "1";
  const s = EDIT.eng.snapshot(); const sets = s.sets.concat(s.curGames[0] || s.curGames[1] ? [s.curGames] : []);
  const rows = (sets.length ? sets : [[0, 0]]).map((g, i) => `<div class="row" style="margin-top:6px">
    <input type="number" min="0" value="${g[0]}" id="gs${i}_1" style="text-align:center">–
    <input type="number" min="0" value="${g[1]}" id="gs${i}_2" style="text-align:center"></div>`).join("");
  box.innerHTML = `<div class="muted" style="margin-top:8px">${EDIT.side1.map(p => esc(p.name)).join(" & ")} — ${EDIT.side2.map(p => esc(p.name)).join(" & ")}</div>
    <div id="gridRows" data-n="${sets.length || 1}">${rows}</div>
    <div class="row" style="margin-top:6px"><button class="btn ghost sm" onclick="gridAdd()">+ Add set</button>
      <button class="btn sm" onclick="gridSave()">Save</button></div>`;
}
function gridAdd() { const r = document.getElementById("gridRows"); const n = +r.dataset.n; if (n >= 5) return; r.dataset.n = n + 1; r.appendChild(el(`<div class="row" style="margin-top:6px"><input type="number" min="0" value="0" id="gs${n}_1" style="text-align:center">–<input type="number" min="0" value="0" id="gs${n}_2" style="text-align:center"></div>`)); }
async function gridSave() {
  const r = document.getElementById("gridRows"); const n = +r.dataset.n; const sets = [];
  for (let i = 0; i < n; i++) sets.push([+document.getElementById(`gs${i}_1`).value || 0, +document.getElementById(`gs${i}_2`).value || 0]);
  try { await api(`/g/${GROUP.code}/api/match/${EDIT.mid}/sets`, { sets }); EDIT = null; loadEditor(); } catch (e) { document.getElementById("edErr").textContent = e; }
}
async function finishMatch() {
  try { await api(`/g/${GROUP.code}/api/match/${EDIT.mid}/finish`, {}); EDIT = null; await refreshMeta(); renderCourt(); loadEditor(); }
  catch (e) { const n = document.getElementById("edErr"); if (n) n.textContent = e; }
}
async function deleteMatch() {
  try { await api(`/g/${GROUP.code}/api/match/${EDIT.mid}/delete`, {}); EDIT = null; await refreshMeta(); renderCourt(); loadEditor(); } catch (e) { }
}

// ---- TT editor ----
function renderTTEditor(msg, confirm) {
  const host = document.getElementById("liveEditor"); const m = EDIT; const c = m.cur; const s = m.game.snapshot();
  host.innerHTML = `<div class="card">
    <div class="edhead">Triple threat · Game ${m.gameNo + 1} <span class="syncchip synced" id="syncChip">● synced</span></div>
    <div class="server">🎾 ${esc(m.names[c.server])} serves · ${esc(m.names[c.receiver])} receives · ${esc(m.names[c.sitter])} sits out</div>
    <div class="bigscore">${esc(s.pointLabel)}</div>
    <div id="ttMsg" class="note">${msg || ""}</div><div id="ttButtons"></div>
    <div class="row" style="margin-top:10px"><button class="btn sm ghost" onclick="deleteMatch()">Delete</button>
      <button class="btn sm" onclick="finishMatch()">Mark finished</button></div><div class="err" id="edErr"></div></div>`;
  const btns = document.getElementById("ttButtons");
  if (confirm) { renderRotationConfirm(btns, confirm); return; }
  btns.innerHTML = `<div class="row"><button class="btn clay" onclick="ttPoint(1)">Point ${esc(m.names[c.server])} 🎾</button>
    <button class="btn clay" onclick="ttPoint(2)">Point ${esc(m.names[c.receiver])}</button></div>
    <button class="btn ghost sm" style="margin-top:8px;width:auto" onclick="ttPointUndo()">↶ Undo point</button>`;
}
function ttPoint(side) {
  const s = EDIT.game.addPoint(side);
  const won = (s.curGames[0] + s.curGames[1]) >= 1;   // a single game completed
  if (won) { const winnerId = s.curGames[0] === 1 ? EDIT.cur.server : EDIT.cur.receiver; onTTGameWon(winnerId); }
  else renderTTEditor();
}
function ttPointUndo() { EDIT.game.undo(); renderTTEditor(); }
function onTTGameWon(winnerId) {
  const c = EDIT.cur, m = EDIT;
  const std = { server: c.receiver, receiver: c.sitter, sitter: c.server };
  const prompt = `Standard rotation for game ${m.gameNo + 2}: 🎾 ${esc(m.names[std.server])} serves → ${esc(m.names[std.receiver])} receives · ${esc(m.names[std.sitter])} sits out. Is that what's happening on court?`;
  renderTTEditor(`✔ ${esc(m.names[winnerId])} won game ${m.gameNo + 1}`, { winnerId, std, prompt });
}
function renderRotationConfirm(host, conf) {
  host.innerHTML = `<div class="note">${conf.prompt}</div>
    <div class="row" style="margin-top:6px"><button class="btn clay" onclick="ttApply()">Yes</button>
      <button class="btn ghost" onclick="ttPickRotation()">No — set it myself</button></div>`;
  EDIT._pending = conf;
}
function ttPickRotation() {
  const m = EDIT; const host = document.getElementById("ttButtons"); EDIT._pick = { server: null, receiver: null };
  const opts = role => m.rot.map(id => `<button class="chip pickchip" onclick="ttPickSet('${role}',${id},this)">${esc(m.names[id])}</button>`).join("");
  host.innerHTML = `<div class="muted">Who serves?</div><div class="chips">${opts('server')}</div>
    <div class="muted" style="margin-top:6px">Who receives?</div><div class="chips">${opts('receiver')}</div>
    <div class="note" id="pickSit">Sits out: (automatic)</div>
    <button class="btn" id="pickConfirm" style="margin-top:6px" disabled onclick="ttApplyCustom()">Confirm</button>`;
}
function ttPickSet(role, id, btn) {
  EDIT._pick[role] = id;
  btn.parentElement.querySelectorAll(".pickchip").forEach(b => b.classList.remove("sel")); btn.classList.add("sel");
  const p = EDIT._pick;
  if (p.server && p.receiver && p.server !== p.receiver) {
    const sit = EDIT.rot.find(x => x !== p.server && x !== p.receiver);
    document.getElementById("pickSit").textContent = "Sits out: " + EDIT.names[sit] + " (automatic)";
    document.getElementById("pickConfirm").disabled = false;
  } else document.getElementById("pickConfirm").disabled = true;
}
function ttApply() { const conf = EDIT._pending; commitTTGame(conf.winnerId); EDIT.cur = conf.std; nextTTGame(); }
function ttApplyCustom() {
  const p = EDIT._pick; const sit = EDIT.rot.find(x => x !== p.server && x !== p.receiver);
  commitTTGame(EDIT._pending.winnerId); EDIT.cur = { server: p.server, receiver: p.receiver, sitter: sit }; nextTTGame();
}
function commitTTGame(winnerId) {
  enqueue(`/g/${GROUP.code}/api/match/${EDIT.mid}/tt`, { server: EDIT.cur.server, receiver: EDIT.cur.receiver, winner: winnerId });
  EDIT.gameNo += 1;
}
function nextTTGame() { EDIT.game = new Engine.PointMatch("singles", [EDIT.cur.server, EDIT.cur.receiver]); EDIT._pending = null; EDIT._pick = null; renderTTEditor(); }

// ---- already played ----
function buildPlayed() {
  document.getElementById("playedCard").innerHTML = `
    <div class="muted">Use the pickers above to choose players, then enter the final score.</div>
    <div id="playedRows"><div class="row" style="margin-top:6px"><input type="number" min="0" value="0" id="ps0_1" style="text-align:center">–<input type="number" min="0" value="0" id="ps0_2" style="text-align:center"></div></div>
    <div class="row" style="margin-top:6px"><button class="btn ghost sm" onclick="playedAdd()">+ Add set</button></div>
    <div class="row" style="margin-top:6px"><input type="date" id="playedDate"><input type="time" id="playedTime"></div>
    <button class="btn" style="margin-top:8px" onclick="savePlayed()">Save result</button>
    <div class="err" id="playedErr"></div>`;
  const now = new Date(); const pad = n => String(n).padStart(2, "0");
  document.getElementById("playedDate").value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  document.getElementById("playedTime").value = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
  document.getElementById("playedRows").dataset.n = 1;
}
function playedAdd() { const r = document.getElementById("playedRows"); const n = +r.dataset.n; if (n >= 5) return; r.dataset.n = n + 1; r.appendChild(el(`<div class="row" style="margin-top:6px"><input type="number" min="0" value="0" id="ps${n}_1" style="text-align:center">–<input type="number" min="0" value="0" id="ps${n}_2" style="text-align:center"></div>`)); }
async function savePlayed() {
  const err = document.getElementById("playedErr"); err.textContent = ""; err.style.color = "";
  if (NEW.kind === "tt") { err.textContent = "triple threat is scored live only"; return; }
  if (NEW.slots.some(x => !x)) { err.textContent = "fill every slot in the picker above"; return; }
  const r = document.getElementById("playedRows"); const n = +r.dataset.n; const sets = [];
  for (let i = 0; i < n; i++) sets.push([+document.getElementById(`ps${i}_1`).value || 0, +document.getElementById(`ps${i}_2`).value || 0]);
  const date = document.getElementById("playedDate").value, time = document.getElementById("playedTime").value;
  const body = Object.assign({}, startPayload(), { sets, played_on: date + (time ? " " + time : "") });
  try { await api(`/g/${GROUP.code}/api/played`, body); err.style.color = "var(--live)"; err.textContent = "Saved ✔"; await refreshMeta(); renderCourt(); }
  catch (e) { err.textContent = e; }
}
