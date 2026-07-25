import { useState } from "react";

/* ── Rally · old deployed UI · v5 (round-5 fixes) ── */
const T = {
  clay: "#A94E2F", clayDeep: "#7C371F", sand: "#F6F0E9", cream: "#FFFDF9",
  ink: "#2B211C", muted: "#8A7B70", yellow: "#D6ED17", line: "#EADFD2",
  team1: "#C86A45", team2: "#8A3B22", live: "#2FB36B", gold: "#E9B949",
  court: "#B65C3B", courtDark: "#9C4A2C", courtLine: "rgba(255,255,255,.9)",
};
const F = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
const GROUP = ["Kabir", "Soumik", "Arjun", "Riya"];
const PTS = ["0", "15", "30", "40"];

const Card = ({ children, style, onClick }) => (
  <div onClick={onClick} style={{ background: T.cream, borderRadius: 16, padding: 14,
    margin: "12px 16px", boxShadow: "0 1px 3px rgba(0,0,0,.06)", ...style }}>{children}</div>
);
const SecTitle = ({ children }) => (
  <div style={{ fontSize: 13, fontWeight: 800, color: T.clayDeep, margin: "16px 16px 4px",
    textTransform: "uppercase", letterSpacing: ".04em" }}>{children}</div>
);
const Btn = ({ kind = "yellow", sm, style, ...p }) => (
  <button {...p} style={{
    fontFamily: F, fontWeight: 800, border: "none", cursor: "pointer", borderRadius: 12,
    padding: sm ? "8px 12px" : "12px 16px", fontSize: sm ? 13 : 15, width: sm ? "auto" : "100%",
    ...(kind === "yellow" && { background: T.yellow, color: "#20260a" }),
    ...(kind === "ghost" && { background: "#fff", border: `1.5px solid ${T.line}`, color: T.ink }),
    ...(p.disabled && { opacity: 0.45, cursor: "default" }), ...style,
  }} />
);
const Seg = ({ options, value, onChange }) => (
  <div style={{ display: "flex", gap: 6 }}>
    {options.map((o) => (
      <button key={o} onClick={() => onChange(o)} style={{
        flex: 1, padding: 8, borderRadius: 10, fontFamily: F, fontWeight: 700, fontSize: 12,
        cursor: "pointer", border: `1.5px solid ${value === o ? T.clay : T.line}`,
        background: value === o ? T.clay : "#fff", color: value === o ? "#fff" : T.ink,
      }}>{o}</button>
    ))}
  </div>
);
const Avatar = ({ n, big }) => (
  <span style={{ width: big ? 34 : 24, height: big ? 34 : 24, borderRadius: "50%",
    background: T.clay, color: "#fff", fontSize: big ? 15 : 11, fontWeight: 800,
    display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{n[0]}</span>
);
const Pill = ({ children }) => (
  <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 20,
    background: "#ffe", color: "#8a6d00" }}>{children}</span>
);
const LiveDot = () => (
  <span style={{ width: 8, height: 8, borderRadius: "50%", background: T.live,
    display: "inline-block", marginLeft: 5 }} />
);
const Empty = ({ children }) => (
  <div style={{ color: T.muted, textAlign: "center", padding: "22px 12px", fontSize: 14 }}>{children}</div>
);

/* demo pair chemistry: key = sorted "A|B" → { score, n } */
const PAIRS = { "Kabir|Riya": { score: 9, n: 4 }, "Kabir|Soumik": { score: -3, n: 3 } };
const chemistry = (a, b) => {
  if (!a || !b) return null;
  const k = [a, b].sort().join("|");
  const pr = PAIRS[k];
  if (!pr || pr.n < 3) return { unexplored: true, need: pr ? 3 - pr.n : 3 };
  return { score: pr.score };
};

/* ── court picker ── */
function CourtPicker({ kind, slots, setSlots, serve, setServe }) {
  const need = kind === "Singles" ? ["A", "B"]
    : kind === "Doubles" ? ["B-ad", "B-deuce", "A-deuce", "A-ad"]
    : ["serve", "receive", "sit"];
  const placed = Object.values(slots);
  const nextEmpty = need.find((k) => !slots[k]);
  const tapChip = (p) => {
    if (placed.includes(p)) {
      setSlots(Object.fromEntries(Object.entries(slots).filter(([, v]) => v !== p)));
      if (serve === p) setServe(null);
    } else if (nextEmpty) {
      const s = { ...slots, [nextEmpty]: p };
      setSlots(s);
      if (kind === "Triple threat" && nextEmpty === "serve") setServe(p);
    }
  };
  const Slot = ({ k, label, small, bench }) => (
    <button onClick={() => slots[k] && kind !== "Triple threat" && setServe(slots[k])} style={{
      flex: 1, minHeight: small ? 50 : 60, cursor: "pointer", fontFamily: F,
      background: slots[k] ? (bench ? T.sand : "rgba(255,253,249,.95)") : bench ? "#fff" : "rgba(255,255,255,.14)",
      border: `2px ${slots[k] ? "solid" : "dashed"} ${bench ? T.line : T.courtLine}`, borderRadius: 10,
      color: slots[k] ? T.ink : bench ? T.muted : "rgba(255,255,255,.85)", fontWeight: 800, fontSize: 13,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      gap: 1, padding: 4, position: "relative",
    }}>
      {label && <span style={{ fontSize: 9, fontWeight: 800, opacity: .8, letterSpacing: 1 }}>{label}</span>}
      {slots[k] ? <>
        {serve === slots[k] && !bench && <span style={{ position: "absolute", top: -9, right: -5, fontSize: 15 }}>🎾</span>}
        {slots[k]}
        {kind !== "Triple threat" && <span style={{ fontSize: 9, fontWeight: 700, color: T.muted }}>tap = serve</span>}
      </> : <span style={{ fontSize: 11, fontWeight: 700 }}>tap to place</span>}
    </button>
  );
  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 10 }}>
        {GROUP.map((p) => {
          const on = placed.includes(p);
          return (
            <button key={p} onClick={() => tapChip(p)} style={{
              border: `1.5px solid ${on ? T.clay : T.line}`, borderRadius: 20,
              background: on ? T.clay : "#fff", color: on ? "#fff" : T.ink,
              padding: "7px 12px", fontSize: 13, fontFamily: F, fontWeight: 700, cursor: "pointer",
            }}>{p}</button>
          );
        })}
      </div>
      <div style={{ marginTop: 10, background: `linear-gradient(180deg, ${T.courtDark}, ${T.court})`,
        border: `3px solid ${T.courtLine}`, borderRadius: 8, padding: 8 }}>
        {kind === "Triple threat" ? (
          <>
            <div style={{ display: "flex", gap: 6 }}><Slot k="receive" label="RECEIVES" /></div>
            <div style={{ margin: "7px -8px", height: 9, background:
              "repeating-linear-gradient(90deg, rgba(255,255,255,.9) 0 2px, rgba(0,0,0,.25) 2px 6px)",
              borderTop: "2px solid #fff", borderBottom: "2px solid #fff" }} />
            <div style={{ display: "flex", gap: 6 }}><Slot k="serve" label="SERVES 🎾" /></div>
          </>
        ) : (
          <>
            <div style={{ textAlign: "center", fontSize: 10, fontWeight: 800, letterSpacing: 2,
              color: "rgba(255,255,255,.85)", marginBottom: 5 }}>
              {kind === "Doubles" ? "TEAM 2" : "SIDE 2"}</div>
            <div style={{ display: "flex", gap: 6 }}>
              {kind === "Singles" ? <Slot k="B" /> : <><Slot k="B-ad" small label="AD" /><Slot k="B-deuce" small label="DEUCE" /></>}
            </div>
            <div style={{ margin: "7px -8px", height: 9, background:
              "repeating-linear-gradient(90deg, rgba(255,255,255,.9) 0 2px, rgba(0,0,0,.25) 2px 6px)",
              borderTop: "2px solid #fff", borderBottom: "2px solid #fff" }} />
            <div style={{ display: "flex", gap: 6 }}>
              {kind === "Singles" ? <Slot k="A" /> : <><Slot k="A-deuce" small label="DEUCE" /><Slot k="A-ad" small label="AD" /></>}
            </div>
            <div style={{ textAlign: "center", fontSize: 10, fontWeight: 800, letterSpacing: 2,
              color: "rgba(255,255,255,.85)", marginTop: 5 }}>
              {kind === "Doubles" ? "TEAM 1" : "SIDE 1"} <span style={{ opacity: .7 }}>(you)</span></div>
          </>
        )}
      </div>
      {kind === "Triple threat" && (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <Slot k="sit" label="SITS OUT · NEXT IN" bench />
        </div>
      )}
      {kind === "Doubles" && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
          {[["TEAM 1", slots["A-deuce"], slots["A-ad"], T.team1],
            ["TEAM 2", slots["B-deuce"], slots["B-ad"], T.team2]].map(([lab, p1, p2, col]) => {
            const c = chemistry(p1, p2);
            return (
              <div key={lab} style={{ display: "flex", alignItems: "center", gap: 8,
                background: "#fff", border: `1.5px solid ${T.line}`, borderRadius: 10,
                padding: "7px 10px" }}>
                <span style={{ fontSize: 11, fontWeight: 800, color: col, width: 52 }}>{lab}</span>
                <span style={{ fontSize: 12, fontWeight: 800, color: T.muted, flex: 1 }}>Chemistry</span>
                {!c ? (
                  <span style={{ fontSize: 12, color: T.muted }}>pick both players</span>
                ) : c.unexplored ? (
                  <span style={{ fontSize: 12, fontWeight: 800, color: T.muted }}>
                    Unexplored — {c.need} more match{c.need > 1 ? "es" : ""} needed</span>
                ) : (
                  <span style={{ fontSize: 15, fontWeight: 900,
                    color: c.score >= 0 ? T.live : "#c0392b" }}>
                    {c.score > 0 ? `+${c.score}` : c.score}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── tennis engine (singles/doubles per-point) ── */
function useTennis() {
  const [s, setS] = useState({ a: 0, b: 0, gA: 0, gB: 0, adv: null });
  const [h, setH] = useState([]);
  const point = (side) => {
    setH((x) => [...x, s]);
    setS((x) => {
      let { a, b, gA, gB, adv } = x;
      const me = side === "A"; const pa = me ? a : b, pb = me ? b : a;
      let win = false;
      if (pa >= 3 && pb >= 3) { if (adv === side) { win = true; adv = null; } else if (!adv) adv = side; else adv = null; }
      else if (pa === 3) win = true; else me ? (a += 1) : (b += 1);
      if (win) { a = 0; b = 0; adv = null; me ? (gA += 1) : (gB += 1); }
      return { a, b, gA, gB, adv };
    });
  };
  const undo = () => setH((x) => { if (!x.length) return x; setS(x[x.length - 1]); return x.slice(0, -1); });
  const lbl = (side) => {
    if (s.a >= 3 && s.b >= 3) return !s.adv ? "40" : s.adv === side ? "Ad" : "–";
    return PTS[side === "A" ? s.a : s.b];
  };
  return { s, point, undo, canUndo: h.length > 0, lbl };
}

/* ── TRIPLE THREAT editor — tennis scoring per game, only the format rotates ── */
function TTEditor({ rotation, onEnd }) {
  const [roles, setRoles] = useState({ s: rotation[0], r: rotation[1], x: rotation[2] });
  const [game, setGame] = useState(1);
  const [pts, setPts] = useState({ a: 0, b: 0, adv: null }); // a = server, b = receiver
  const [hist, setHist] = useState([]);
  const [tally, setTally] = useState(Object.fromEntries(rotation.map((p) => [p, 0])));
  const [stage, setStage] = useState("play"); // play | confirm | custom
  const [lastWinner, setLastWinner] = useState(null);
  const [pick, setPick] = useState({ s: null, r: null });
  const standardNext = { s: roles.r, r: roles.x, x: roles.s };

  const lbl = (side) => {
    if (pts.a >= 3 && pts.b >= 3) return !pts.adv ? "40" : pts.adv === side ? "Ad" : "–";
    return PTS[side === "a" ? pts.a : pts.b];
  };
  const point = (side) => {
    setHist((h) => [...h, { pts }]);
    let { a, b, adv } = pts;
    const me = side === "a";
    const pa = me ? a : b, pb = me ? b : a;
    let win = false;
    if (pa >= 3 && pb >= 3) { if (adv === side) { win = true; } else if (!adv) adv = side; else adv = null; }
    else if (pa === 3) win = true;
    else { me ? (a += 1) : (b += 1); }
    if (win) {
      const winner = me ? roles.s : roles.r;
      setTally((t) => ({ ...t, [winner]: t[winner] + 1 }));
      setLastWinner(winner);
      setStage("confirm");
      setPts({ a: 0, b: 0, adv: null });
      setHist([]);
    } else setPts({ a, b, adv });
  };
  const undo = () => setHist((h) => {
    if (!h.length) return h;
    setPts(h[h.length - 1].pts);
    return h.slice(0, -1);
  });
  const apply = (next) => {
    setRoles(next); setGame(game + 1); setPts({ a: 0, b: 0, adv: null });
    setHist([]); setStage("play"); setPick({ s: null, r: null });
  };
  const impliedSit = pick.s && pick.r ? rotation.find((p) => p !== pick.s && p !== pick.r) : null;

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 800, fontSize: 14 }}>Triple threat · Game {game}</span>
        <span style={{ fontSize: 10, fontWeight: 800, color: "#fff", background: T.live,
          borderRadius: 20, padding: "2px 8px" }}>LIVE</span>
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        {rotation.map((p) => (
          <span key={p} style={{ flex: 1, textAlign: "center", fontSize: 12, fontWeight: 800,
            background: T.sand, borderRadius: 8, padding: "5px 0" }}>
            {p} <span style={{ color: T.clay }}>{tally[p]}</span></span>
        ))}
      </div>

      {stage === "play" && (
        <>
          {/* same tennis scoring as singles/doubles — only the format rotates */}
          <div style={{ textAlign: "center", fontWeight: 900, fontSize: 38, margin: "10px 0 2px" }}>
            {lbl("a")} <span style={{ color: T.clay }}>·</span> {lbl("b")}
          </div>
          <div style={{ textAlign: "center", fontSize: 12, color: T.muted }}>
            🎾 {roles.s} serving → {roles.r} · {roles.x} sits out
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Btn kind="ghost" style={{ flex: 1, width: "auto" }} onClick={() => point("a")}>+ {roles.s}</Btn>
            <Btn kind="ghost" style={{ flex: 1, width: "auto" }} onClick={() => point("b")}>+ {roles.r}</Btn>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Btn kind="ghost" sm disabled={!hist.length} onClick={undo} style={{ flex: 1 }}>↩ Undo</Btn>
            <Btn kind="ghost" sm onClick={onEnd} style={{ flex: 1, borderColor: "#d9534f", color: "#c0392b" }}>End match</Btn>
          </div>
        </>
      )}

      {stage === "confirm" && (
        <div style={{ marginTop: 10, border: `2px solid ${T.clay}`, borderRadius: 12, padding: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 800 }}>
            ✔ {lastWinner} won game {game}.
          </div>
          <div style={{ fontSize: 13, marginTop: 6 }}>
            Standard rotation for game {game + 1}:<br />
            🎾 <b>{standardNext.s}</b> serves → <b>{standardNext.r}</b> receives ·{" "}
            <b>{standardNext.x}</b> sits out
          </div>
          <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>
            Is that what's happening on court?
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Btn sm style={{ flex: 1 }} onClick={() => apply(standardNext)}>Yes</Btn>
            <Btn kind="ghost" sm style={{ flex: 1 }} onClick={() => setStage("custom")}>
              No — set it myself</Btn>
          </div>
        </div>
      )}

      {stage === "custom" && (
        <div style={{ marginTop: 10, border: `2px solid ${T.clay}`, borderRadius: 12, padding: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 800 }}>Who's doing what in game {game + 1}?</div>
          {[["s", "Serves 🎾"], ["r", "Receives"]].map(([role, lab]) => (
            <div key={role} style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
              <span style={{ width: 76, fontSize: 12, fontWeight: 800, color: T.muted }}>{lab}</span>
              {rotation.map((p) => {
                const taken = Object.entries(pick).some(([k, v]) => v === p && k !== role);
                const on = pick[role] === p;
                return (
                  <button key={p} disabled={taken} onClick={() => setPick({ ...pick, [role]: p })}
                    style={{ flex: 1, padding: "7px 0", borderRadius: 10, fontFamily: F,
                      fontWeight: 700, fontSize: 12, cursor: taken ? "default" : "pointer",
                      opacity: taken ? 0.35 : 1,
                      border: `1.5px solid ${on ? T.clay : T.line}`,
                      background: on ? T.clay : "#fff", color: on ? "#fff" : T.ink }}>
                    {p}</button>
                );
              })}
            </div>
          ))}
          {/* third role auto-implied */}
          <div style={{ marginTop: 8, fontSize: 12, fontWeight: 800, color: T.muted }}>
            Sits out: <span style={{ color: T.ink }}>{impliedSit || "—"}</span>
            {impliedSit && <span style={{ fontWeight: 600 }}> (automatic)</span>}
          </div>
          <Btn sm style={{ marginTop: 10, width: "100%" }} disabled={!impliedSit}
            onClick={() => apply({ s: pick.s, r: pick.r, x: impliedSit })}>
            Confirm — serve tracking follows this</Btn>
        </div>
      )}
    </Card>
  );
}

/* ── LOG tab ── */
function LogTab({ live, setLive }) {
  const [kind, setKind] = useState("Singles");
  const [slots, setSlots] = useState({});
  const [serve, setServe] = useState(null);
  const [entry, setEntry] = useState("point");
  const [grid, setGrid] = useState([["", ""], ["", ""], ["", ""]]);
  const needN = kind === "Singles" ? 2 : kind === "Doubles" ? 4 : 3;
  const ready = Object.keys(slots).length === needN && serve;
  const tennis = useTennis();

  return (
    <div>
      <SecTitle>Start a live match</SecTitle>
      <Card>
        <Seg options={["Singles", "Doubles", "Triple threat"]} value={kind}
          onChange={(k) => { setKind(k); setSlots({}); setServe(null); }} />
        <div style={{ fontSize: 13, color: T.muted, marginTop: 10 }}>
          {kind === "Triple threat"
            ? "Place all 3: who serves first, who receives, who sits."
            : "Tap players onto the court. Tap a placed player to give them the 🎾 first serve."}
        </div>
        <CourtPicker kind={kind} slots={slots} setSlots={setSlots} serve={serve} setServe={setServe} />
        <div style={{ fontSize: 11, color: T.muted, marginTop: 8 }}>
          Someone missing? Players are added by the app admin — not from inside the group.
        </div>
        {live && (
          <div style={{ marginTop: 10, padding: "8px 10px", borderRadius: 10, background: T.sand,
            fontSize: 12, fontWeight: 800, color: T.muted }}>
            ✔ Match started — score it in "Update the live match" just below. Finish it to start another.
          </div>
        )}
        <Btn style={{ marginTop: 10 }} disabled={!!live || !ready}
          onClick={() => {
            if (kind === "Triple threat")
              setLive({ kind, rotation: [slots["serve"], slots["receive"], slots["sit"]] });
            else {
              const v = Object.values(slots);
              setLive({ kind, a: v[v.length - 1], b: v[0], server: serve });
            }
          }}>{live ? "A match is already live" : "▶ Start"}</Btn>
      </Card>

      <SecTitle>Update the live match</SecTitle>
      {!live ? (
        <Card style={{ padding: 0 }}><Empty>No live match yet — start one above.</Empty></Card>
      ) : live.kind === "Triple threat" ? (
        <TTEditor key={live.rotation.join("-")} rotation={live.rotation} onEnd={() => setLive(null)} />
      ) : (
        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 14 }}>
              <Avatar n={live.a} /> {live.a}</span>
            <span style={{ fontSize: 10, fontWeight: 800, color: "#fff", background: T.live,
              borderRadius: 20, padding: "2px 8px" }}>LIVE</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 14 }}>
              {live.b} <Avatar n={live.b} /></span>
          </div>
          <div style={{ textAlign: "center", fontWeight: 900, fontSize: 34, margin: "8px 0 2px" }}>
            {tennis.lbl("A")} <span style={{ color: T.clay }}>·</span> {tennis.lbl("B")}
          </div>
          <div style={{ textAlign: "center", fontSize: 12, color: T.muted }}>
            Games {tennis.s.gA}–{tennis.s.gB} · 🎾 {live.server} serving</div>
          <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
            {[["point", "Per point"], ["sets", "Set scores"]].map(([k, t]) => (
              <button key={k} onClick={() => setEntry(k)} style={{
                flex: 1, padding: 7, borderRadius: 10, fontFamily: F, fontWeight: 700, fontSize: 12,
                cursor: "pointer", border: `1.5px solid ${entry === k ? T.clay : T.line}`,
                background: entry === k ? T.clay : "#fff", color: entry === k ? "#fff" : T.ink,
              }}>{t}</button>
            ))}
          </div>
          {entry === "point" ? (
            <>
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <Btn kind="ghost" style={{ flex: 1, width: "auto" }} onClick={() => tennis.point("A")}>+ {live.a}</Btn>
                <Btn kind="ghost" style={{ flex: 1, width: "auto" }} onClick={() => tennis.point("B")}>+ {live.b}</Btn>
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <Btn kind="ghost" sm disabled={!tennis.canUndo} onClick={tennis.undo} style={{ flex: 1 }}>↩ Undo</Btn>
                <Btn kind="ghost" sm onClick={() => setLive(null)} style={{ flex: 1, borderColor: "#d9534f", color: "#c0392b" }}>End</Btn>
              </div>
            </>
          ) : (
            <>
              <div style={{ marginTop: 10, border: `1px solid ${T.line}`, borderRadius: 12, overflow: "hidden" }}>
                <div style={{ display: "flex", background: T.sand, fontSize: 11, fontWeight: 800,
                  color: T.muted, padding: "5px 10px" }}>
                  <span style={{ flex: 1 }} />
                  <span style={{ width: 40, textAlign: "center" }}>S1</span>
                  <span style={{ width: 40, textAlign: "center" }}>S2</span>
                  <span style={{ width: 40, textAlign: "center" }}>S3</span>
                </div>
                {[live.a, live.b].map((nm, r) => (
                  <div key={nm} style={{ display: "flex", alignItems: "center", padding: "6px 10px",
                    borderTop: `1px solid ${T.line}`, background: "#fff" }}>
                    <span style={{ flex: 1, fontWeight: 700, fontSize: 13, display: "flex",
                      alignItems: "center", gap: 6 }}><Avatar n={nm} /> {nm}</span>
                    {[0, 1, 2].map((c) => (
                      <input key={c} value={grid[c][r]} inputMode="numeric"
                        onChange={(e) => {
                          const g2 = grid.map((x) => [...x]);
                          g2[c][r] = e.target.value.slice(0, 2);
                          setGrid(g2);
                        }}
                        style={{ width: 34, margin: "0 3px", textAlign: "center", font: "inherit",
                          fontWeight: 800, padding: "6px 0", border: `1.5px solid ${T.line}`,
                          borderRadius: 8, background: T.sand, color: T.ink }} />
                    ))}
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <Btn sm style={{ flex: 1 }}>Save sets</Btn>
                <Btn kind="ghost" sm onClick={() => setLive(null)} style={{ flex: 1, borderColor: "#d9534f", color: "#c0392b" }}>End</Btn>
              </div>
            </>
          )}
        </Card>
      )}

      <SecTitle>Already played? Final score</SecTitle>
      <PlayedCard />
    </div>
  );
}

/* ── past result entry (working) ── */
function PlayedCard() {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState([]);
  const [pg, setPg] = useState([["", ""], ["", ""], ["", ""]]);
  const [date, setDate] = useState("2026-07-24");
  const [time, setTime] = useState("18:45");
  const [saved, setSaved] = useState(false);
  const tap = (p) => setPicked(picked.includes(p)
    ? picked.filter((x) => x !== p)
    : picked.length < 2 ? [...picked, p] : picked);
  return (
    <Card>
      {!open ? (
        <>
          <div style={{ fontSize: 13, color: T.muted }}>Same pickers, then enter the final sets.</div>
          <Btn kind="ghost" sm style={{ marginTop: 8 }} onClick={() => setOpen(true)}>Enter a past result</Btn>
        </>
      ) : saved ? (
        <div style={{ fontSize: 14, fontWeight: 800 }}>✔ Result saved — see it in History.</div>
      ) : (
        <>
          <div style={{ fontSize: 13, color: T.muted }}>Pick the two players (first picked = side 1):</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 8 }}>
            {GROUP.map((p) => (
              <button key={p} onClick={() => tap(p)} style={{
                border: `1.5px solid ${picked.includes(p) ? T.clay : T.line}`, borderRadius: 20,
                background: picked.includes(p) ? T.clay : "#fff",
                color: picked.includes(p) ? "#fff" : T.ink,
                padding: "7px 12px", fontSize: 13, fontFamily: F, fontWeight: 700, cursor: "pointer",
              }}>{p}</button>
            ))}
          </div>
          {picked.length === 2 && (
            <>
              <div style={{ marginTop: 10, border: `1px solid ${T.line}`, borderRadius: 12, overflow: "hidden" }}>
                <div style={{ display: "flex", background: T.sand, fontSize: 11, fontWeight: 800,
                  color: T.muted, padding: "5px 10px" }}>
                  <span style={{ flex: 1 }} />
                  <span style={{ width: 40, textAlign: "center" }}>S1</span>
                  <span style={{ width: 40, textAlign: "center" }}>S2</span>
                  <span style={{ width: 40, textAlign: "center" }}>S3</span>
                </div>
                {picked.map((nm, r) => (
                  <div key={nm} style={{ display: "flex", alignItems: "center", padding: "6px 10px",
                    borderTop: `1px solid ${T.line}`, background: "#fff" }}>
                    <span style={{ flex: 1, fontWeight: 700, fontSize: 13 }}>{nm}</span>
                    {[0, 1, 2].map((c) => (
                      <input key={c} value={pg[c][r]} inputMode="numeric"
                        onChange={(e) => { const g2 = pg.map((x) => [...x]);
                          g2[c][r] = e.target.value.slice(0, 2); setPg(g2); }}
                        style={{ width: 34, margin: "0 3px", textAlign: "center", font: "inherit",
                          fontWeight: 800, padding: "6px 0", border: `1.5px solid ${T.line}`,
                          borderRadius: 8, background: T.sand, color: T.ink }} />
                    ))}
                  </div>
                ))}
              </div>
              {/* native calendar + clock pickers, prefilled with auto date/time */}
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                  style={{ flex: 1, font: "inherit", fontSize: 13, padding: "9px 10px",
                    border: `1.5px solid ${T.line}`, borderRadius: 12, background: "#fff", color: T.ink }} />
                <input type="time" value={time} onChange={(e) => setTime(e.target.value)}
                  style={{ flex: 1, font: "inherit", fontSize: 13, padding: "9px 10px",
                    border: `1.5px solid ${T.line}`, borderRadius: 12, background: "#fff", color: T.ink }} />
              </div>
              <Btn sm style={{ marginTop: 10, width: "100%" }} onClick={() => setSaved(true)}>Save result</Btn>
            </>
          )}
        </>
      )}
    </Card>
  );
}

/* ── funnel drawer ── */
function FunnelDrawer({ open, close, mode, setMode, scope, setScope, modes }) {
  return (
    <>
      <div onClick={close} style={{ position: "absolute", inset: 0, background: "rgba(43,33,28,.45)",
        opacity: open ? 1 : 0, pointerEvents: open ? "auto" : "none", transition: "opacity .2s" }} />
      <div style={{ position: "absolute", top: 0, bottom: 0, right: 0, width: "74%",
        background: T.cream, borderLeft: `1px solid ${T.line}`, padding: 16,
        transform: open ? "translateX(0)" : "translateX(105%)", transition: "transform .22s ease",
        display: "flex", flexDirection: "column", gap: 14, zIndex: 5 }}>
        <div style={{ fontWeight: 800, fontSize: 15 }}>Filters</div>
        <FG label="Mode">{modes.map((x) => (
          <FC key={x} on={mode === x} onClick={() => setMode(x)}>{x}</FC>))}</FG>
        <FG label="Who">{["This group", "Everyone"].map((x) => (
          <FC key={x} on={scope === x} onClick={() => setScope(x)}>{x}</FC>))}</FG>
        <Btn onClick={close} style={{ marginTop: "auto" }}>Apply</Btn>
      </div>
    </>
  );
}
const FG = ({ label, children }) => (
  <div>
    <div style={{ fontSize: 11, letterSpacing: 1.5, textTransform: "uppercase", color: T.muted,
      marginBottom: 8, fontWeight: 800 }}>{label}</div>
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>{children}</div>
  </div>
);
const FC = ({ on, onClick, children }) => (
  <button onClick={onClick} style={{ display: "flex", alignItems: "center", gap: 10,
    background: "transparent", border: "none", cursor: "pointer", padding: 0,
    color: on ? T.ink : T.muted, fontFamily: F, fontSize: 14, fontWeight: 700 }}>
    <span style={{ width: 20, height: 20, borderRadius: 5, flexShrink: 0,
      border: `2px solid ${on ? T.clay : T.line}`, background: on ? T.clay : "#fff",
      color: "#fff", fontSize: 13, lineHeight: "17px", textAlign: "center", fontWeight: 900 }}>
      {on ? "✓" : ""}</span>{children}</button>
);
const Funnel = ({ onClick }) => (
  <button onClick={onClick} aria-label="Filters" style={{
    width: 44, height: 44, borderRadius: 12, cursor: "pointer", flexShrink: 0,
    border: `1.5px solid ${T.line}`, background: "#fff", color: T.clay,
    fontSize: 16, fontWeight: 900 }}>▼</button>
);

/* ── RANKS ── */
const LBD = [
  { name: "Soumik", pts: 64, n: 9, playing: true },
  { name: "Kabir", pts: 41, n: 8, playing: true },
];
const PROV = [{ name: "Riya", pts: -18, n: 5, playing: true },
  { name: "Arjun", pts: 0, n: 0, playing: true }];
function RanksTab({ openPlayer }) {
  const [drawer, setDrawer] = useState(false);
  const [scope, setScope] = useState("This group");
  const [mode, setMode] = useState("Singles");
  const Row = ({ r, i, prov }) => (
    <div onClick={() => openPlayer(r)} style={{ display: "flex", alignItems: "center", gap: 10,
      padding: "10px 12px", borderBottom: `1px solid ${T.line}`, cursor: "pointer" }}>
      <span style={{ width: 22, fontWeight: 800, color: T.muted }}>{prov ? "–" : i + 1}</span>
      <Avatar n={r.name} />
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>{r.name}{r.playing && <LiveDot />}</div>
        <div style={{ fontSize: 12, color: T.muted }}>tap for stats</div>
      </div>
      <span style={{ fontWeight: 900, fontSize: 18,
        color: r.pts > 0 ? T.ink : r.pts < 0 ? "#c0392b" : T.muted }}>
        {r.pts > 0 ? `+${r.pts}` : r.pts}</span>
    </div>
  );
  return (
    <div style={{ position: "relative", minHeight: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", gap: 8, margin: "14px 16px 0", alignItems: "center" }}>
        <input placeholder="Search players…" style={{ flex: 1, font: "inherit", padding: "11px 12px",
          border: `1.5px solid ${T.line}`, borderRadius: 12, background: "#fff", color: T.ink }} />
        <Funnel onClick={() => setDrawer(true)} />
      </div>
      <div style={{ margin: "6px 16px 0", fontSize: 12, color: T.muted }}>{mode} · {scope}</div>
      <Card style={{ padding: "0 4px" }}>{LBD.map((r, i) => <Row key={r.name} r={r} i={i} />)}</Card>
      <SecTitle>Minimum 5 matches</SecTitle>
      <Card style={{ padding: "0 4px" }}>{PROV.map((r, i) => <Row key={r.name} r={r} i={i} prov />)}</Card>
      <FunnelDrawer open={drawer} close={() => setDrawer(false)} mode={mode} setMode={setMode}
        scope={scope} setScope={setScope} modes={["Singles", "Doubles"]} />
    </div>
  );
}

/* ── PLAYER STATS ── */
function PlayerStats({ p, back }) {
  return (
    <div>
      <div style={{ margin: "12px 16px 0" }}>
        <Btn kind="ghost" sm onClick={back}>← Ranks</Btn>
      </div>
      <Card>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 18, fontWeight: 800 }}>
          <Avatar n={p.name} big /> {p.name}{p.playing && <LiveDot />}
          {p.name === "Kabir" && <span style={{ fontSize: 10, fontWeight: 800, color: "#fff",
            background: T.gold, borderRadius: 20, padding: "2px 8px" }}>YOU</span>}
        </div>
        <div style={{ color: T.muted, fontSize: 13, marginTop: 6 }}>
          5W · 3L · last 5:{" "}
          {["W", "W", "L", "W", "L"].map((r, i) => (
            <b key={i} style={{ color: r === "W" ? T.live : "#c0392b" }}>{r} </b>
          ))}
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 12 }}>
          <div><div style={{ color: T.muted, fontSize: 12 }}>Singles</div>
            <div style={{ fontSize: 22, fontWeight: 900 }}>{p.pts > 0 ? `+${p.pts}` : p.pts}</div>
            {p.n < 5 && <Pill>{p.n} of 5</Pill>}</div>
          <div><div style={{ color: T.muted, fontSize: 12 }}>Doubles</div>
            <div style={{ fontSize: 22, fontWeight: 900 }}>+12</div></div>
        </div>
      </Card>
      <SecTitle>Pair ratings</SecTitle>
      <Card style={{ padding: "6px 12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
          <span style={{ fontSize: 14 }}>with {p.name === "Soumik" ? "Kabir" : "Soumik"}</span>
          <span style={{ fontWeight: 800 }}>+9 <Pill>2/3</Pill></span>
        </div>
      </Card>
      <SecTitle>Serve &amp; return</SecTitle>
      <Card>
        <div style={{ display: "flex", gap: 24 }}>
          <div><div style={{ color: T.muted, fontSize: 12 }}>Hold %</div>
            <div style={{ fontSize: 20, fontWeight: 900 }}>67</div></div>
          <div><div style={{ color: T.muted, fontSize: 12 }}>Break %</div>
            <div style={{ fontSize: 20, fontWeight: 900 }}>38</div></div>
        </div>
        <div style={{ fontSize: 11, color: T.muted, marginTop: 6 }}>from 4 live-scored matches</div>
      </Card>
      <SecTitle>Matches</SecTitle>
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 14 }}>
          <span>{p.name}</span><span style={{ color: T.muted }}>6–4 · 3–6 · 7–5</span>
          <span>{p.name === "Soumik" ? "Kabir" : "Soumik"}</span>
        </div>
        <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>24 Jul · 6:45 PM · singles</div>
      </Card>
    </div>
  );
}

/* ── HISTORY (funnel + editable date/time) ── */
function HistoryRow({ a, b, score, kind, when }) {
  const [editing, setEditing] = useState(false);
  const [dt, setDt] = useState(when);
  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 14 }}>
        <span>{a}</span><span style={{ color: T.muted }}>{score}</span><span>{b}</span>
      </div>
      <div style={{ fontSize: 12, color: T.muted, marginTop: 4, display: "flex",
        alignItems: "center", gap: 6 }}>
        {!editing ? (
          <>
            <span>{dt} · {kind}</span>
            <button onClick={() => setEditing(true)} style={{ border: "none", background: "none",
              cursor: "pointer", fontSize: 12, color: T.clay, fontWeight: 800 }}>✎ edit</button>
          </>
        ) : (
          <>
            <input type="date" defaultValue="2026-07-24"
              style={{ font: "inherit", fontSize: 12, padding: "4px 8px",
                border: `1.5px solid ${T.line}`, borderRadius: 8 }} />
            <input type="time" defaultValue="18:45"
              style={{ font: "inherit", fontSize: 12, padding: "4px 8px",
                border: `1.5px solid ${T.line}`, borderRadius: 8 }} />
            <Btn sm onClick={() => { setDt("24 Jul · 6:45 PM"); setEditing(false); }}>Save</Btn>
          </>
        )}
      </div>
    </Card>
  );
}
function HistoryTab() {
  const [drawer, setDrawer] = useState(false);
  const [scope, setScope] = useState("This group");
  const [mode, setMode] = useState("All");
  return (
    <div style={{ position: "relative", minHeight: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "12px 16px 0" }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: T.clayDeep, textTransform: "uppercase",
          letterSpacing: ".04em", flex: 1 }}>History <span style={{ color: T.muted, fontWeight: 600,
          textTransform: "none" }}>· {mode} · {scope}</span></span>
        <Funnel onClick={() => setDrawer(true)} />
      </div>
      <HistoryRow a="Kabir" b="Soumik" score="6–4 · 3–6 · 7–5" kind="singles"
        when="24 Jul · 6:45 PM (auto)" />
      <HistoryRow a="Riya + Kabir" b="Soumik + Arjun" score="4–6 · 6–7" kind="doubles"
        when="20 Jul · 5:10 PM (auto)" />
      <FunnelDrawer open={drawer} close={() => setDrawer(false)} mode={mode} setMode={setMode}
        scope={scope} setScope={setScope} modes={["All", "Singles", "Doubles", "Triple threat"]} />
    </div>
  );
}

/* ── LIVE tab: broadcast grids, 🎾 marks the server, no empty sections ── */
const ScoreGrid = ({ rows, kind, started, prob }) => (
  <Card style={{ padding: 0, overflow: "hidden" }}>
    <div style={{ display: "flex", alignItems: "center", padding: "7px 12px", background: T.sand }}>
      <span style={{ fontSize: 11, fontWeight: 800, color: T.muted, flex: 1, textTransform: "uppercase",
        letterSpacing: 1 }}>{kind} · started {started}</span>
      <span style={{ fontSize: 10, fontWeight: 800, color: "#fff", background: T.live,
        borderRadius: 20, padding: "2px 8px" }}>LIVE</span>
    </div>
    {rows.map((r, i) => (
      <div key={i} style={{ display: "flex", alignItems: "center", padding: "9px 12px",
        borderTop: `1px solid ${T.line}`, background: "#fff" }}>
        <span style={{ flex: 1, fontWeight: 700, fontSize: 14, lineHeight: 1.25 }}>
          {r.names.map((n) => (
            <span key={n} style={{ display: "block" }}>
              {n}{r.serveName === n && <span style={{ marginLeft: 5 }}>🎾</span>}
            </span>
          ))}
        </span>
        {r.sets.map((s, j) => (
          <span key={j} style={{ width: 30, textAlign: "center", fontWeight: 800, fontSize: 15,
            color: r.won && r.won.includes(j) ? T.clay : T.ink }}>{s}</span>
        ))}
        <span style={{ width: 38, textAlign: "center", fontWeight: 900, fontSize: 15,
          color: "#fff", background: T.clay, borderRadius: 8, padding: "4px 0",
          marginLeft: 6 }}>{r.pts}</span>
      </div>
    ))}
    {prob && (
      <div style={{ padding: "8px 12px", borderTop: `1px solid ${T.line}`, background: "#fff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11,
          fontWeight: 800, color: T.muted, marginBottom: 4 }}>
          <span>{rows[0].names.join(" & ")} · {prob[0]}%</span>
          <span>{prob[1]}% · {rows[1].names.join(" & ")}</span>
        </div>
        <div style={{ display: "flex", height: 8, borderRadius: 6, overflow: "hidden" }}>
          <span style={{ width: `${prob[0]}%`, background: T.live }} />
          <span style={{ flex: 1, background: T.line }} />
        </div>
        <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>
          updates live with every point, from ratings + current score
        </div>
      </div>
    )}
  </Card>
);

const PUBLIC_LIVE = []; // nothing live elsewhere → section renders NOTHING at all
const LiveTab = () => (
  <div>
    <SecTitle>Live now</SecTitle>
    <ScoreGrid kind="Singles" started="6:41 PM" prob={[58, 42]} rows={[
      { names: ["Kabir"], serveName: "Kabir", sets: ["0"], pts: "0" },
      { names: ["Arjun"], sets: ["0"], pts: "0" },
    ]} />
    {/* Triple threat live card */}
    <Card style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", padding: "7px 12px", background: T.sand }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: T.muted, flex: 1,
          textTransform: "uppercase", letterSpacing: 1 }}>Triple threat · started 5:55 PM</span>
        <span style={{ fontSize: 10, fontWeight: 800, color: "#fff", background: T.live,
          borderRadius: 20, padding: "2px 8px" }}>LIVE</span>
      </div>
      <div style={{ display: "flex", gap: 6, padding: "8px 12px 0" }}>
        {[["Soumik", 3], ["Riya", 2], ["Tara", 1]].map(([p, g]) => (
          <span key={p} style={{ flex: 1, textAlign: "center", fontSize: 12, fontWeight: 800,
            background: T.sand, borderRadius: 8, padding: "5px 0" }}>
            {p} <span style={{ color: T.clay }}>{g}</span></span>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", padding: "9px 12px" }}>
        <span style={{ flex: 1, fontWeight: 700, fontSize: 14 }}>Soumik 🎾</span>
        <span style={{ fontWeight: 900, fontSize: 18 }}>30 <span style={{ color: T.clay }}>·</span> 40</span>
        <span style={{ flex: 1, fontWeight: 700, fontSize: 14, textAlign: "right" }}>Riya</span>
      </div>
      <div style={{ padding: "0 12px 6px", fontSize: 12, color: T.muted }}>
        Game 7 · Tara sits out
      </div>
      <div style={{ padding: "8px 12px", borderTop: `1px solid ${T.line}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11,
          fontWeight: 800, color: T.muted, marginBottom: 4 }}>
          <span>Soumik · 46%</span><span>Riya · 33%</span><span>Tara · 21%</span>
        </div>
        <div style={{ display: "flex", height: 8, borderRadius: 6, overflow: "hidden" }}>
          <span style={{ width: "46%", background: T.live }} />
          <span style={{ width: "33%", background: T.gold }} />
          <span style={{ flex: 1, background: T.line }} />
        </div>
        <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>
          updates live with every point, from ratings + games won
        </div>
      </div>
    </Card>
    <ScoreGrid kind="Doubles" started="6:12 PM" prob={[74, 26]} rows={[
      { names: ["Riya", "Ishaan"], serveName: "Riya", sets: ["6", "3"], won: [0], pts: "30" },
      { names: ["Soumik", "Tara"], sets: ["4", "4"], won: [1], pts: "15" },
    ]} />
    {PUBLIC_LIVE.length > 0 && (
      <>
        <SecTitle>From public groups — watch only</SecTitle>
        {PUBLIC_LIVE.map((m, i) => <ScoreGrid key={i} {...m} />)}
      </>
    )}
  </div>
);

/* ── GROUPS: create + join working, visibility toggle, no admin ── */
function GroupsTab({ groups, setGroups, groupName }) {
  const [joinOpen, setJoinOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [code, setCode] = useState("");
  const [newName, setNewName] = useState("");
  const [justCreated, setJustCreated] = useState(null);

  const doJoin = () => {
    if (code.trim().length >= 4) {
      setGroups([...groups, { name: `Group ${code.trim().toUpperCase()}`, code: code.trim().toUpperCase(), pub: false }]);
      setCode(""); setJoinOpen(false);
    }
  };
  const doCreate = () => {
    if (newName.trim()) {
      const c = Math.random().toString(36).slice(2, 8).toUpperCase();
      setGroups([...groups, { name: newName.trim(), code: c, pub: false }]);
      setJustCreated({ name: newName.trim(), code: c });
      setNewName(""); setCreateOpen(false);
    }
  };
  const flip = (g) => setGroups(groups.map((x) => x.code === g.code ? { ...x, pub: !x.pub } : x));

  return (
    <div>
      <SecTitle>You</SecTitle>
      <Card>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Avatar n="Kabir" />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 14 }}>Kabir <span style={{ fontSize: 10,
              fontWeight: 800, color: "#fff", background: T.gold, borderRadius: 20,
              padding: "2px 8px" }}>YOU</span></div>
            <div style={{ fontSize: 12, color: T.muted }}>claimed on this phone</div>
          </div>
          <Btn kind="ghost" sm>Change</Btn>
        </div>
      </Card>

      {justCreated && (
        <Card style={{ border: `2px solid ${T.clay}` }}>
          <div style={{ fontWeight: 800, fontSize: 14 }}>✔ {justCreated.name} created</div>
          <div style={{ fontSize: 13, marginTop: 4 }}>Share this code with your friends:{" "}
            <b style={{ fontSize: 16, letterSpacing: 2 }}>{justCreated.code}</b></div>
        </Card>
      )}

      <SecTitle>Your groups</SecTitle>
      {groups.map((g) => (
        <Card key={g.code}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 14 }}>🎾 {g.name}
                {g.name === groupName && <span style={{ fontSize: 10, color: T.live,
                  fontWeight: 800 }}> · current</span>}</div>
              <div style={{ fontSize: 12, color: T.muted }}>code {g.code} · {g.pub ? "public" : "private"}</div>
            </div>
            <Btn kind="ghost" sm onClick={() => flip(g)}>
              {g.pub ? "Make private" : "Make public"}</Btn>
          </div>
        </Card>
      ))}

      <Card>
        {!createOpen ? (
          <Btn kind="ghost" sm onClick={() => { setCreateOpen(true); setJoinOpen(false); }}>+ Create a group</Btn>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Group name"
              style={{ flex: 1, font: "inherit", padding: "11px 12px",
                border: `1.5px solid ${T.line}`, borderRadius: 12, background: "#fff", color: T.ink }} />
            <Btn sm onClick={doCreate}>Create</Btn>
          </div>
        )}
        <div style={{ height: 8 }} />
        {!joinOpen ? (
          <Btn kind="ghost" sm onClick={() => { setJoinOpen(true); setCreateOpen(false); }}>+ Join another group</Btn>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Group code"
              style={{ flex: 1, font: "inherit", padding: "11px 12px", textTransform: "uppercase",
                border: `1.5px solid ${T.line}`, borderRadius: 12, background: "#fff", color: T.ink }} />
            <Btn sm onClick={doJoin}>Join</Btn>
          </div>
        )}
      </Card>
    </div>
  );
}

export default function RallyOldUiV5() {
  const [tab, setTab] = useState("log");
  const [live, setLive] = useState(null);
  const [player, setPlayer] = useState(null);
  const [switcher, setSwitcher] = useState(false);
  const [groups, setGroups] = useState([
    { name: "Salt Lake Crew", code: "JFDFEG", pub: false },
    { name: "Park Circus Pals", code: "QX21AB", pub: true },
  ]);
  const [groupName, setGroupName] = useState("Salt Lake Crew");
  const cur = groups.find((g) => g.name === groupName) || groups[0];
  const TABS = [["🎾", "Live", "live"], ["🏆", "Ranks", "ranks"], ["✏️", "Log", "log"],
    ["👥", "Groups", "groups"], ["📜", "History", "history"]];
  return (
    <div style={{ minHeight: "100vh", background: "#EDE4D8", padding: "16px 10px 40px", fontFamily: F }}>
      <div style={{ maxWidth: 412, margin: "0 auto" }}>
        <div style={{ color: T.clayDeep, fontWeight: 800, fontSize: 13, letterSpacing: 2,
          textTransform: "uppercase" }}>Rally · v5</div>
        <div style={{ color: T.muted, fontSize: 13, margin: "6px 0 12px" }}>
          TT fixed end-to-end · groups create/join/switch/visibility · 🎾 = who's serving · green dot = playing now.
        </div>
        <div style={{ borderRadius: 24, overflow: "hidden", background: T.sand, height: 690,
          display: "flex", flexDirection: "column", boxShadow: "0 16px 44px rgba(43,33,28,.28)",
          border: `1px solid ${T.line}`, position: "relative" }}>
          <div style={{ background: `linear-gradient(180deg, ${T.clay}, ${T.clayDeep})`, color: "#fff",
            padding: "8px 16px 12px" }}>
            <div onClick={() => setSwitcher(true)} style={{ fontSize: 18, fontWeight: 800,
              cursor: "pointer" }}>🎾 {groupName} <span style={{ opacity: .7, fontSize: 13 }}>▾</span></div>
            <div style={{ fontSize: 12, opacity: .85 }}>code <b>{cur.code}</b> · {cur.pub ? "public" : "private"}</div>
            <div style={{ height: 2, background: "rgba(255,255,255,.5)", marginTop: 8, borderRadius: 2 }} />
          </div>
          <div style={{ flex: 1, minHeight: 0, overflowY: "auto", paddingBottom: 8, position: "relative" }}>
            {player ? <PlayerStats p={player} back={() => setPlayer(null)} /> : <>
              {tab === "live" && <LiveTab />}
              {tab === "ranks" && <RanksTab openPlayer={setPlayer} />}
              {tab === "log" && <LogTab live={live} setLive={setLive} />}
              {tab === "groups" && <GroupsTab groups={groups} setGroups={setGroups} groupName={groupName} />}
              {tab === "history" && <HistoryTab />}
            </>}
          </div>
          {switcher && (
            <div onClick={(e) => e.target === e.currentTarget && setSwitcher(false)} style={{
              position: "absolute", inset: 0, background: "rgba(43,33,28,.5)", zIndex: 20,
              display: "flex", alignItems: "flex-end" }}>
              <div style={{ background: T.cream, width: "100%", borderRadius: "18px 18px 0 0",
                padding: 16 }}>
                <div style={{ fontWeight: 800, marginBottom: 10 }}>Your groups</div>
                {groups.map((g) => (
                  <div key={g.code} onClick={() => { setGroupName(g.name); setSwitcher(false); }}
                    style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 4px",
                      borderTop: `1px solid ${T.line}`, cursor: "pointer" }}>
                    <Avatar n={g.name} />
                    <span style={{ flex: 1, fontWeight: 700, fontSize: 14 }}>{g.name}</span>
                    {g.name === groupName && <span style={{ color: T.live, fontWeight: 900 }}>✓</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          <nav style={{ display: "flex", background: T.cream, borderTop: `1px solid ${T.line}` }}>
            {TABS.map(([ic, t, k]) => (
              <button key={k} onClick={() => { setTab(k); setPlayer(null); }} style={{
                flex: 1, textAlign: "center", padding: "8px 2px 10px", fontSize: 10, cursor: "pointer",
                background: "transparent", border: "none", fontFamily: F,
                color: tab === k ? T.clay : T.muted, fontWeight: tab === k ? 800 : 600,
              }}><span style={{ display: "block", fontSize: 18 }}>{ic}</span>{t}</button>
            ))}
          </nav>
        </div>
      </div>
    </div>
  );
}
