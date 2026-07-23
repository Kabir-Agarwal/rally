"use strict";
// tennis-scores client. No prompt/alert/confirm anywhere — inline inputs + errors only.

// ---- storage ----
const LS = {
  groups(){ try{return JSON.parse(localStorage.getItem("ts_groups")||"[]")}catch(e){return[]} },
  addGroup(g){ const gs=LS.groups().filter(x=>x.code!==g.code); gs.unshift(g); localStorage.setItem("ts_groups",JSON.stringify(gs)); },
  me(code){ return localStorage.getItem("ts_me_"+code); },
  setMe(code,pid){ localStorage.setItem("ts_me_"+code,pid); },
};
async function api(url,body){
  const opt=body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{};
  const r=await fetch(url,opt); const j=await r.json().catch(()=>({}));
  if(!r.ok) throw (j.error||("error "+r.status)); return j;
}
const el=(h)=>{const d=document.createElement("div");d.innerHTML=h.trim();return d.firstChild;};
const esc=(s)=>String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const av=(n)=>`<span class="avatar">${esc((n||"?")[0]).toUpperCase()}</span>`;

// ---- landing ----
async function doCreate(){
  const name=document.getElementById("grpName").value.trim();
  const err=document.getElementById("createErr"); err.textContent="";
  if(!name){err.textContent="name required";return;}
  try{
    const g=await api("/api/group/create",{name});
    LS.addGroup(g);
    document.getElementById("createForm").style.display="none";
    document.getElementById("createDone").style.display="block";
    document.getElementById("newCode").textContent=g.code;
    document.getElementById("enterBtn").onclick=()=>location.href="/g/"+g.code+"/live";
  }catch(e){err.textContent=e;}
}
async function doJoin(){
  const code=document.getElementById("joinCode").value.trim().toUpperCase();
  const err=document.getElementById("joinErr"); err.textContent="";
  try{ const g=await api("/api/group/join",{code}); LS.addGroup(g); location.href="/g/"+g.code+"/live"; }
  catch(e){err.textContent=e;}
}
function renderMyGroups(){
  const host=document.getElementById("myGroups"); if(!host) return;
  const gs=LS.groups(); if(!gs.length){host.innerHTML="";return;}
  host.innerHTML=`<div class="sec-title">Your groups</div>`;
  const card=el(`<div class="card" style="padding:4px 4px"></div>`);
  gs.forEach(g=>card.appendChild(el(
    `<div class="lbrow" onclick="location.href='/g/${g.code}/live'"><div class="nm">${esc(g.name)}</div><div class="tag">${g.code}</div></div>`)));
  host.appendChild(card);
}

// ---- switcher ----
function openSwitcher(){
  const s=document.getElementById("switcher"); if(!s)return; s.classList.add("open");
  const list=document.getElementById("switcherList"); const gs=LS.groups();
  list.innerHTML = gs.length?"":"No other groups yet.";
  gs.forEach(async g=>{
    const row=el(`<div class="grp"><span class="gname">${esc(g.name)}</span>
      <span class="dotwrap"></span>
      <button class="btn sm ghost" onclick="location.href='/g/${g.code}/live'">Switch</button></div>`);
    list.appendChild(row);
    try{ const d=await api(`/g/${g.code}/api/live`); if(d.matches.length) row.querySelector(".dotwrap").innerHTML='<span class="dot pulse"></span>'; }catch(e){}
  });
}
function closeSwitcher(){ const s=document.getElementById("switcher"); if(s)s.classList.remove("open"); }

// ---- polling ----
function poll(fn,ms){ fn(); let t=setInterval(()=>{ if(!document.hidden) fn(); },ms||3000); return t; }

// ---- match card (read-only scoresheet) ----
function matchCard(m,opts){
  opts=opts||{};
  const live = m.status==="live";
  let head=`<div class="names">`;
  if(m.kind==="tt"){
    head+=`<div class="side">${m.rotation.map(r=>av(r.name)+esc(r.name)).join(" · ")}</div>`;
  }else{
    const s1=m.side1.map(p=>av(p.name)+esc(p.name)).join(" & ");
    const s2=m.side2.map(p=>av(p.name)+esc(p.name)).join(" & ");
    const w1=m.winner_side===1, w2=m.winner_side===2;
    head+=`<div class="side">${w1?'<span class="dot win"></span>':''}${s1}${w1?' 🏆':''}</div>`;
    head+=`<div class="side" style="justify-content:flex-end">${s2}${w2?' 🏆':''}${w2?'<span class="dot win"></span>':''}</div>`;
  }
  head+= live?`<span class="pill live">LIVE</span>`:(opts.tag?`<span class="tag">${esc(opts.tag)}</span>`:"");
  head+=`</div>`;

  let body="";
  if(m.kind==="tt"){
    body=`<div class="ttboard">`;
    if(m.pairing) body+=`<div class="server">🎾 ${esc(m.pairing.server)} serves vs ${esc(m.pairing.receiver)} · ${esc(m.pairing.sitter)} sits</div>`;
    body+=`<div class="row" style="gap:8px;margin-top:6px">`+
      m.tally.map(t=>`<div class="setcell">${esc(t.name)}: ${t.wins}</div>`).join("")+`</div></div>`;
  }else{
    body=`<div class="sheet"><div class="setcol">`+
      m.sets.map(s=>`<div class="setcell ${s.won1?'won':''}">${s.g1}</div>`).join("")+`</div><div class="setcol">`+
      m.sets.map(s=>`<div class="setcell ${s.won2?'won':''}">${s.g2}</div>`).join("")+`</div>`;
    if(m.per_point && live) body+=`<div class="pointboard" style="flex:1"><div class="pointscore">${esc(m.point_score||"")}</div></div>`;
    body+=`</div>`;
    if(m.per_point && m.server && live) body+=`<div class="server">🎾 ${esc(m.server)} serving${m.is_tiebreak?' · tiebreak':''}</div>`;
  }
  const tagline = m.kind.toUpperCase()+(m.played_on?" · "+m.played_on:"");
  return el(`<div class="match">${head}${body}<div class="note">${tagline}${opts.group?' · '+esc(opts.group):''}</div>${opts.extra||""}</div>`);
}

// ================= LIVE =================
function initLive(){
  poll(async()=>{
    const d=await api(`/g/${GROUP.code}/api/live`);
    const host=document.getElementById("liveMatches");
    host.innerHTML="";
    if(!d.matches.length) host.appendChild(el(`<div class="empty">No live matches. Start one in Log.</div>`));
    d.matches.forEach(m=>host.appendChild(matchCard(m)));
    const pub=document.getElementById("publicMatches"); pub.innerHTML="";
    if(!d.public.length) pub.appendChild(el(`<div class="empty">Nothing live elsewhere.</div>`));
    d.public.forEach(m=>pub.appendChild(matchCard(m,{group:m.group})));
  });
}

// ================= LEADERBOARD =================
let LB={scope:"group",mode:"singles",data:null};
function setScope(b){document.querySelectorAll("#lbScope button").forEach(x=>x.classList.remove("on"));b.classList.add("on");LB.scope=b.dataset.scope;loadLeaderboard();}
function setMode(b){document.querySelectorAll("#lbMode button").forEach(x=>x.classList.remove("on"));b.classList.add("on");LB.mode=b.dataset.mode;loadLeaderboard();}
async function loadLeaderboard(){
  LB.data=await api(`/g/${GROUP.code}/api/leaderboard?scope=${LB.scope}&mode=${LB.mode}`);
  document.getElementById("scopeNote").textContent = LB.scope==="everyone"
    ? "Everyone = players from public groups, tagged by group." : "";
  renderLeaderboard();
}
function lbRow(r,me){
  const you=r.id==me && LB.scope==="group";
  const dot=r.live?'<span class="dot pulse"></span>':'';
  const tag=r.group?`<span class="tag">${esc(r.group)}</span>`:'';
  return `<div class="lbrow ${you?'you':''}" onclick="location.href='/g/${GROUP.code}/player/${r.id}'">
    <div class="rk">${r.rank||''}</div><div class="nm">${dot}${esc(r.name)}${tag}${you?' <span class="youpill">YOU</span>':''}</div>
    <div class="rt">${r.rating}</div></div>`;
}
function renderLeaderboard(){
  if(!LB.data)return; const me=LS.me(GROUP.code); const q=(document.getElementById("lbSearch").value||"").toLowerCase();
  const filt=(a)=>a.filter(r=>r.name.toLowerCase().includes(q));
  const ranked=filt(LB.data.ranked), prov=filt(LB.data.provisional);
  // subway-surfers you-card with true rank
  const yc=document.getElementById("youCard"); yc.innerHTML="";
  if(me && LB.scope==="group"){
    const you=LB.data.ranked.find(r=>r.id==me);
    if(you) yc.appendChild(el(`<div class="youcard">${av(you.name)}<div style="flex:1"><b>${esc(you.name)}</b> <span class="youpill">YOU</span></div>
      <div>#${you.rank} · <b>${you.rating}</b></div></div>`));
  }
  const list=document.getElementById("lbList");
  list.innerHTML = ranked.length? ranked.map(r=>lbRow(r,me)).join("") : `<div class="empty">No ranked players yet.</div>`;
  const pl=document.getElementById("lbProv");
  pl.innerHTML = prov.length? prov.map(r=>`<div class="lbrow" onclick="location.href='/g/${GROUP.code}/player/${r.id}'">
    <div class="rk">–</div><div class="nm">${r.live?'<span class="dot pulse"></span>':''}${esc(r.name)}${r.group?`<span class="tag">${esc(r.group)}</span>`:''}</div>
    <div class="rt">${r.rating} <span class="pill">${r.n}/5</span></div></div>`).join("") : `<div class="empty">—</div>`;
}
function initLeaderboard(){
  loadLeaderboard();
  poll(async()=>{
    const d=await api(`/g/${GROUP.code}/api/live`);
    const strip=document.getElementById("lbLive");
    if(!d.matches.length){strip.innerHTML='<span class="muted">No live matches.</span>';return;}
    strip.innerHTML=d.matches.map(m=>{
      let line = m.kind==="tt"
        ? m.tally.map(t=>esc(t.name)+" "+t.wins).join(" · ")
        : esc((m.side1[0]||{}).name)+" vs "+esc((m.side2[0]||{}).name)+(m.per_point?"  "+esc(m.point_score||""):"");
      return `<div class="lbrow" style="padding:6px 4px" onclick="location.href='/g/${GROUP.code}/live'"><span class="pill live">LIVE</span>&nbsp;<div class="nm">${line}</div></div>`;
    }).join("");
  });
}

// ================= LOG =================
let NEW={kind:"singles",picked:[],ratings:{singles:{},doubles:{}}};
function setKind(b){document.querySelectorAll("#kindSeg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");NEW.kind=b.dataset.kind;NEW.picked=[];renderPicker();}
function needCount(){return NEW.kind==="singles"?2:NEW.kind==="tt"?3:4;}
function renderPicker(){
  const host=document.getElementById("picker"); const need=needCount();
  document.getElementById("pickHint").textContent =
    NEW.kind==="singles"?"Pick 2 players in serving order (P1 serves first)."
    :NEW.kind==="tt"?"Pick 3 in rotation order.":"Pick 4 in serving order: T1, T2, T1, T2.";
  host.innerHTML="";
  PLAYERS.forEach(p=>{
    const idx=NEW.picked.indexOf(p.id);
    const sel=idx>=0;
    // team coloring for doubles/singles by serving slot parity
    let cls="chip";
    if(sel && NEW.kind!=="tt"){ cls+= (idx%2===0)?" t1":" t2"; }
    else if(sel) cls+=" t1";
    if(sel) cls+=" sel";
    const badge=sel?`<span class="badge">${idx+1}</span>`:"";
    host.appendChild(el(`<div class="${cls}" onclick="pick(${p.id})">${esc(p.name)}${badge}</div>`));
  });
  updateWinProb();
}
function pick(id){
  const i=NEW.picked.indexOf(id);
  if(i>=0){NEW.picked.splice(i,1);}
  else if(NEW.picked.length<needCount()){NEW.picked.push(id);}
  renderPicker();
}
function updateWinProb(){
  const wp=document.getElementById("winProb"); if(!wp)return;
  const need=needCount();
  if(NEW.kind==="tt"||NEW.picked.length<need){wp.textContent="";return;}
  const rmap=NEW.ratings.singles, rd=NEW.ratings.doubles;
  let ra,rb;
  if(NEW.kind==="singles"){ra=rmap[NEW.picked[0]]||1200;rb=rmap[NEW.picked[1]]||1200;}
  else{ra=((rd[NEW.picked[0]]||1200)+(rd[NEW.picked[2]]||1200))/2; rb=((rd[NEW.picked[1]]||1200)+(rd[NEW.picked[3]]||1200))/2;}
  const p=Math.round(100/(1+Math.pow(10,(rb-ra)/400)));
  wp.innerHTML=`Win prob — Team 1 ${p}% vs ${100-p}% Team 2 <div style="height:8px;border-radius:6px;background:var(--team2);margin-top:4px"><div style="width:${p}%;height:100%;border-radius:6px;background:var(--team1)"></div></div>`;
}
async function addPlayer(){
  const inp=document.getElementById("newPlayerName"); const name=inp.value.trim();
  const err=document.getElementById("pickErr"); err.textContent="";
  if(!name)return;
  try{ const p=await api(`/g/${GROUP.code}/api/player`,{name}); PLAYERS.push(p); inp.value=""; renderPicker(); }
  catch(e){err.textContent=e;}
}
async function startMatch(){
  const err=document.getElementById("pickErr"); err.textContent="";
  if(NEW.picked.length!==needCount()){err.textContent="pick "+needCount()+" players";return;}
  const me=LS.me(GROUP.code);
  let body={kind:NEW.kind,logger:me?+me:NEW.picked[0]};
  if(NEW.kind==="tt") body.rotation=NEW.picked;
  else if(NEW.kind==="singles"){body.side1=[NEW.picked[0]];body.side2=[NEW.picked[1]];}
  else {body.side1=[NEW.picked[0],NEW.picked[2]];body.side2=[NEW.picked[1],NEW.picked[3]];}
  try{ await api(`/g/${GROUP.code}/api/match/start`,body); NEW.picked=[]; renderPicker(); loadEditors(); }
  catch(e){err.textContent=e;}
}
// live editors
async function loadEditors(){
  const d=await api(`/g/${GROUP.code}/api/live`);
  const host=document.getElementById("liveEditors"); host.innerHTML="";
  if(!d.matches.length){host.innerHTML=`<div class="empty">No live matches. Start one below.</div>`;return;}
  d.matches.forEach(m=>host.appendChild(editorCard(m)));
}
function editorCard(m){
  const card=el(`<div class="card" id="ed${m.id}"></div>`);
  render_editor(card,m);
  return card;
}
function render_editor(card,m){
  const me=LS.me(GROUP.code);
  let title = m.kind==="tt"? m.rotation.map(r=>esc(r.name)).join(" · ")
    : m.side1.map(p=>esc(p.name)).join(" & ")+" vs "+m.side2.map(p=>esc(p.name)).join(" & ");
  card.innerHTML=`<div style="font-weight:800;margin-bottom:6px">${title} <span class="pill live">LIVE</span></div>`;
  const bodyId="body"+m.id;
  card.appendChild(el(`<div id="${bodyId}"></div>`));
  const body=card.querySelector("#"+bodyId);
  if(m.kind==="tt") ttEditor(body,m);
  else { card.dataset.mode=card.dataset.mode||"grid";
    const seg=el(`<div class="seg" style="margin:8px 0"><button class="${card.dataset.mode==='grid'?'on':''}" onclick="setEdMode(${m.id},'grid')">Scoresheet</button><button class="${card.dataset.mode==='point'?'on':''}" onclick="setEdMode(${m.id},'point')">Point-by-point</button></div>`);
    card.insertBefore(seg,body);
    if(card.dataset.mode==="point") pointEditor(body,m); else gridEditor(body,m);
  }
  const foot=el(`<div class="row" style="margin-top:10px">
    <button class="btn sm clay" onclick="markFinished(${m.id})">Mark finished</button>
    <button class="btn sm danger" onclick="delMatch(${m.id})">Delete</button></div><div class="err" id="ederr${m.id}"></div>`);
  card.appendChild(foot);
}
function setEdMode(id,mode){ const c=document.getElementById("ed"+id); c.dataset.mode=mode;
  api(`/g/${GROUP.code}/api/match/${id}`).then(m=>render_editor(c,m)); }
function gridEditor(host,m){
  const sets = m.sets.length?m.sets:[{g1:0,g2:0}];
  let rows=sets.map((s,i)=>`<div class="row" style="margin-top:6px">
    <input type="number" min="0" value="${s.g1}" id="s${m.id}_${i}_1" style="text-align:center">
    <span style="flex:0 0 auto">–</span>
    <input type="number" min="0" value="${s.g2}" id="s${m.id}_${i}_2" style="text-align:center"></div>`).join("");
  host.innerHTML=`<div class="muted">${m.side1.map(p=>esc(p.name)).join(" & ")} — ${m.side2.map(p=>esc(p.name)).join(" & ")}</div>
    <div id="gridrows${m.id}" data-n="${sets.length}">${rows}</div>
    <div class="row" style="margin-top:8px"><button class="btn sm ghost" onclick="addSet(${m.id})">+ Add set</button>
    <button class="btn sm" onclick="saveGrid(${m.id})">Save</button></div>`;
}
function addSet(id){
  const rows=document.getElementById("gridrows"+id); const n=+rows.dataset.n;
  if(n>=5)return; rows.dataset.n=n+1;
  rows.appendChild(el(`<div class="row" style="margin-top:6px">
    <input type="number" min="0" value="0" id="s${id}_${n}_1" style="text-align:center"><span style="flex:0 0 auto">–</span>
    <input type="number" min="0" value="0" id="s${id}_${n}_2" style="text-align:center"></div>`));
}
async function saveGrid(id){
  const rows=document.getElementById("gridrows"+id); const n=+rows.dataset.n; const sets=[];
  for(let i=0;i<n;i++){sets.push([+document.getElementById(`s${id}_${i}_1`).value||0,+document.getElementById(`s${id}_${i}_2`).value||0]);}
  const err=document.getElementById("ederr"+id); err.textContent="";
  try{ await api(`/g/${GROUP.code}/api/match/${id}/sets`,{sets}); flash(id,"Saved"); }catch(e){err.textContent=e;}
}
function flash(id,msg){const e=document.getElementById("ederr"+id);e.style.color="var(--live)";e.textContent=msg;setTimeout(()=>{e.style.color="";e.textContent="";},1200);}
// point-by-point
function pointEditor(host,m){
  const s1=m.side1.map(p=>esc(p.name)).join(" & "), s2=m.side2.map(p=>esc(p.name)).join(" & ");
  host.innerHTML=`<div class="pointboard"><div class="pointscore">${esc(m.point_score||"0-0")}</div>
    <div class="server">${m.server?'🎾 '+esc(m.server)+' serving'+(m.is_tiebreak?' · tiebreak':''):''}</div></div>
    <div class="sheet" style="justify-content:center">
      <div class="setcol">${m.sets.map(s=>`<div class="setcell ${s.won1?'won':''}">${s.g1}</div>`).join("")}</div>
      <div class="setcol">${m.sets.map(s=>`<div class="setcell ${s.won2?'won':''}">${s.g2}</div>`).join("")}</div></div>
    <div class="row" style="margin-top:10px"><button class="btn sm clay" onclick="pt(${m.id},1)">Point ${s1}</button>
    <button class="btn sm clay" onclick="pt(${m.id},2)">Point ${s2}</button></div>
    <button class="btn sm ghost" style="margin-top:8px;width:auto" onclick="ptUndo(${m.id})">↶ Undo</button>`;
}
async function pt(id,side){ const m=await api(`/g/${GROUP.code}/api/match/${id}/point`,{winner_side:side});
  const c=document.getElementById("ed"+id); c.dataset.mode="point"; render_editor(c,m); }
async function ptUndo(id){ const m=await api(`/g/${GROUP.code}/api/match/${id}/point/undo`);
  const c=document.getElementById("ed"+id); c.dataset.mode="point"; render_editor(c,m); }
// tt
function ttEditor(host,m){
  let pairing = m.pairing?`🎾 ${esc(m.pairing.server)} serves vs ${esc(m.pairing.receiver)} · ${esc(m.pairing.sitter)} sits`:"";
  host.innerHTML=`<div class="server">${pairing}</div>
    <div class="row" style="margin-top:6px">${m.tally.map(t=>`<div class="setcell">${esc(t.name)}: ${t.wins}</div>`).join("")}</div>
    <div class="note">Rates completed rounds only.</div>
    <div class="chips" style="margin-top:8px">${m.rotation.map(r=>`<button class="btn sm clay" onclick="ttGame(${m.id},${r.id},${m.pairing?m.pairing.server_id:0})">Game: ${esc(r.name)}</button>`).join("")}</div>
    <button class="btn sm ghost" style="margin-top:8px;width:auto" onclick="ttUndo(${m.id})">↶ Undo</button>`;
}
async function ttGame(id,winner,server){ const m=await api(`/g/${GROUP.code}/api/match/${id}/tt`,{winner,server});
  render_editor(document.getElementById("ed"+id),m); }
async function ttUndo(id){ const m=await api(`/g/${GROUP.code}/api/match/${id}/tt/undo`);
  render_editor(document.getElementById("ed"+id),m); }

async function markFinished(id){
  const me=LS.me(GROUP.code); const err=document.getElementById("ederr"+id); err.textContent="";
  try{ const r=await api(`/g/${GROUP.code}/api/match/${id}/finish`,{logger:me?+me:null}); loadEditors(); }
  catch(e){err.textContent=e;}
}
async function delMatch(id){
  const me=LS.me(GROUP.code);
  try{ await api(`/g/${GROUP.code}/api/match/${id}/delete`,{player:me?+me:null}); loadEditors(); }catch(e){}
}
// already played
function togglePlayed(){ const b=document.getElementById("playedBody"); b.style.display = b.style.display==="none"?"block":"none";
  if(b.dataset.built) return; b.dataset.built=1;
  b.innerHTML=`<div class="muted" style="margin-top:8px">Use the picker above to select players, then enter sets:</div>
    <div id="playedRows"><div class="row" style="margin-top:6px"><input type="number" min="0" value="0" id="ps0_1" style="text-align:center"><span style="flex:0 0 auto">–</span><input type="number" min="0" value="0" id="ps0_2" style="text-align:center"></div></div>
    <div class="row" style="margin-top:8px"><button class="btn sm ghost" onclick="addPlayedSet()">+ Add set</button><button class="btn sm" onclick="savePlayed()">Save result</button></div>
    <div class="err" id="playedErr"></div>`;
  b.dataset.n=1;
}
function addPlayedSet(){ const b=document.getElementById("playedBody"); const n=+b.dataset.n; if(n>=5)return;
  document.getElementById("playedRows").appendChild(el(`<div class="row" style="margin-top:6px"><input type="number" min="0" value="0" id="ps${n}_1" style="text-align:center"><span style="flex:0 0 auto">–</span><input type="number" min="0" value="0" id="ps${n}_2" style="text-align:center"></div>`));
  b.dataset.n=n+1;
}
async function savePlayed(){
  const err=document.getElementById("playedErr"); err.textContent="";
  if(NEW.picked.length!==needCount()){err.textContent="pick "+needCount()+" players above";return;}
  const b=document.getElementById("playedBody"); const n=+b.dataset.n; const sets=[];
  for(let i=0;i<n;i++){sets.push([+document.getElementById(`ps${i}_1`).value||0,+document.getElementById(`ps${i}_2`).value||0]);}
  const me=LS.me(GROUP.code);
  let body={kind:NEW.kind,logger:me?+me:NEW.picked[0],sets};
  if(NEW.kind==="tt"){err.textContent="triple threat is scored live only";return;}
  if(NEW.kind==="singles"){body.side1=[NEW.picked[0]];body.side2=[NEW.picked[1]];}
  else {body.side1=[NEW.picked[0],NEW.picked[2]];body.side2=[NEW.picked[1],NEW.picked[3]];}
  try{ await api(`/g/${GROUP.code}/api/played`,body); err.style.color="var(--live)"; err.textContent="Saved — awaiting approval"; }
  catch(e){err.textContent=e;}
}
async function initLog(){
  // gate + ratings for win prob
  const me=LS.me(GROUP.code);
  if(!me){ document.getElementById("gate").innerHTML=`<div class="card note">Tip: set “which player am I” in Groups so results auto-approve for you.</div>`; }
  try{ const s=await api(`/g/${GROUP.code}/api/leaderboard?scope=group&mode=singles`);
       [...s.ranked,...s.provisional].forEach(r=>NEW.ratings.singles[r.id]=r.rating);
       const d=await api(`/g/${GROUP.code}/api/leaderboard?scope=group&mode=doubles`);
       [...d.ranked,...d.provisional].forEach(r=>NEW.ratings.doubles[r.id]=r.rating);}catch(e){}
  renderPicker(); loadEditors(); setInterval(loadEditors,3000);
}

// ================= GROUPS =================
async function togglePublic(){
  const next=!GROUP.is_public;
  await api(`/g/${GROUP.code}/api/public`,{is_public:next}); GROUP.is_public=next;
  const b=document.getElementById("pubBtn");
  b.className="big-toggle "+(next?"pub":"priv");
  b.textContent=next?"🌐 Public — on global leaderboard":"🔒 Private — members only";
  document.getElementById("pubNote").textContent=next?"Anyone with the link can watch; your players show globally.":"Invisible. Only code-holders see it.";
}
function renderWho(){
  const host=document.getElementById("whoPicker"); const me=LS.me(GROUP.code); host.innerHTML="";
  PLAYERS.forEach(p=>host.appendChild(el(`<div class="chip ${me==p.id?'t1 sel':''}" onclick="setMe(${p.id})">${esc(p.name)}</div>`)));
  if(!PLAYERS.length) host.innerHTML='<span class="muted">Add players in the Log tab first.</span>';
}
function setMe(id){ LS.setMe(GROUP.code,id); renderWho(); }
function renderGroupsList(){
  const host=document.getElementById("groupsList"); const gs=LS.groups(); host.innerHTML="";
  gs.forEach(async g=>{
    const row=el(`<div class="lbrow" style="cursor:default"><div class="nm">${esc(g.name)} <span class="tag">${g.code}</span> <span class="dw"></span></div>
      <button class="btn sm ghost" onclick="location.href='/g/${g.code}/live'">Switch</button></div>`);
    host.appendChild(row);
    try{const d=await api(`/g/${g.code}/api/live`); if(d.matches.length) row.querySelector(".dw").innerHTML='<span class="dot pulse"></span>';}catch(e){}
  });
  if(!gs.length) host.innerHTML='<div class="empty">No groups saved on this device.</div>';
}
async function createFromTab(){
  const name=document.getElementById("gName2").value.trim(); const out=document.getElementById("createOut");
  if(!name){out.textContent="name required";return;}
  try{const g=await api("/api/group/create",{name});LS.addGroup(g);out.innerHTML=`Created <b>${g.code}</b> — <a href="/g/${g.code}/live">enter ▶</a>`;renderGroupsList();}
  catch(e){out.textContent=e;}
}
async function joinFromTab(){
  const code=document.getElementById("jCode2").value.trim().toUpperCase(); const out=document.getElementById("joinOut2"); out.textContent="";
  try{const g=await api("/api/group/join",{code});LS.addGroup(g);location.href="/g/"+g.code+"/live";}catch(e){out.textContent=e;}
}

// ================= HISTORY =================
function reqCard(m){
  const del=m.request_type==="delete";
  const title=del?"🗑 Delete this match?":"🎾 Approve this result?";
  const me=LS.me(GROUP.code);
  const mini=matchCard(m).outerHTML;
  const chips=m.approvals.map(a=>a.approved
    ? `<span class="chip" style="opacity:.6">✓ ${esc(a.name)}</span>`
    : `<button class="chip ok" onclick="approve(${m.id},${a.player_id})">Approve · ${esc(a.name)}</button>`).join("");
  const dl=m.approvals[0]?m.approvals[0].deadline:"";
  return el(`<div class="req ${del?'del':''}"><div class="rhd">${title}<span class="count"> · until ${esc((dl||'').replace('T',' '))}</span></div>
    <div class="rbody">${mini}<div class="approve-chips">${chips}</div></div></div>`);
}
async function approve(id,pid){ try{await api(`/g/${GROUP.code}/api/match/${id}/approve`,{player:pid}); initHistory();}catch(e){} }
async function reqDelete(id){ const me=LS.me(GROUP.code); try{await api(`/g/${GROUP.code}/api/match/${id}/delete`,{player:me?+me:null}); initHistory();}catch(e){} }
function storyLine(s){ if(!s)return"";
  let bits=[]; if(s.holds||s.breaks)bits.push(`held ${s.holds}, broke ${s.breaks}`);
  if(s.saved_game_points)bits.push(`saved ${s.saved_game_points} game pts`);
  if(s.deuce_points)bits.push(`${s.deuce_points} deuce pts`);
  if(s.longest_streak>=4)bits.push(`${s.longest_streak}-point run`);
  return bits.length?`<div class="note">🎾 Live-scored · ${bits.join(" · ")}</div>`:"";
}
async function initHistory(){
  const d=await api(`/g/${GROUP.code}/api/history`);
  const rc=document.getElementById("requests"); rc.innerHTML="";
  if(d.requests.length){rc.appendChild(el(`<div class="sec-title">Needs your tap</div>`)); d.requests.forEach(m=>rc.appendChild(reqCard(m)));}
  const hl=document.getElementById("historyList"); hl.innerHTML="";
  if(!d.matches.length){hl.innerHTML=`<div class="empty">No finished matches yet.</div>`;return;}
  d.matches.forEach(m=>{
    const extra = storyLine(m.story) + `<div class="row" style="margin-top:6px"><button class="btn sm danger" style="width:auto" onclick="reqDelete(${m.id})">Request delete</button></div>`;
    hl.appendChild(matchCard(m,{extra}));
  });
}

// ================= PLAYER =================
function initPlayer(){
  const me=LS.me(GROUP.code);
  if(me==PLAYER.id){const b=document.getElementById("youBadge");if(b)b.innerHTML='<span class="youpill">YOU</span>';}
  const host=document.getElementById("pmHist");
  if(!PLAYER.matches.length){host.innerHTML='<div class="empty">No matches yet.</div>';return;}
  host.innerHTML="";
  PLAYER.matches.forEach(m=>host.appendChild(matchCard(m)));
}

// ---- boot ----
document.addEventListener("DOMContentLoaded",()=>{
  renderMyGroups();
  const p=window.PAGE;
  if(p==="live")initLive();
  else if(p==="leaderboard")initLeaderboard();
  else if(p==="log")initLog();
  else if(p==="groups"){renderWho();renderGroupsList();}
  else if(p==="history")initHistory();
  else if(p==="player")initPlayer();
});
