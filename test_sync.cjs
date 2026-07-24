/* Node test for the background sync queue. Run: node test_sync.cjs */
const assert = require("assert");
const SyncQueue = require("./static/sync.js");

const noSleep = () => Promise.resolve();   // make backoff instant in tests

(async () => {
  // 1) a POST that fails twice then succeeds -> queue retries and the item lands
  let calls = 0;
  const flaky = async () => { calls++; return { ok: calls >= 3, status: calls < 3 ? 500 : 200 }; };
  let statuses = [];
  const q = new SyncQueue({ fetch: flaky, sleep: noSleep, onStatus: s => statuses.push(s) });
  await q.push({ url: "/x", body: { n: 1 } });
  assert.strictEqual(calls, 3, "retried until success");
  assert.strictEqual(q.pending(), 0, "queue drained");
  assert.strictEqual(q.status, "synced", "ends synced");
  assert.ok(statuses.includes("saving") && statuses[statuses.length - 1] === "synced", "status chip: saving -> synced");

  // 2) order preserved across items
  const seen = [];
  const rec = async (url) => { seen.push(url); return { ok: true, status: 200 }; };
  const q2 = new SyncQueue({ fetch: rec, sleep: noSleep });
  const p = [];
  for (let i = 0; i < 5; i++) p.push(q2.push({ url: "/p" + i }));
  await Promise.all(p);
  assert.deepStrictEqual(seen, ["/p0", "/p1", "/p2", "/p3", "/p4"], "FIFO order preserved");

  // 3) exponential backoff delays grow (base*2^(n-1), capped)
  const delays = [];
  const q3 = new SyncQueue({ fetch: async () => ({ ok: false, status: 500 }), sleep: ms => { delays.push(ms); return Promise.resolve(); }, baseDelay: 100, maxDelay: 1000, maxAttempts: 5 });
  await q3.push({ url: "/fail" }).catch(() => { });
  assert.deepStrictEqual(delays, [100, 200, 400, 800], "backoff 100,200,400,800 then give up at maxAttempts");

  console.log("OK sync (node)");
})().catch(e => { console.error(e); process.exit(1); });
