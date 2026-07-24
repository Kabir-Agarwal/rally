/* Rally background sync queue (Task 2b).
   The UI updates instantly from the client engine; writes are enqueued here and POSTed in
   the background with async retry + exponential backoff. Transport (fetch) is injectable so
   it runs headless in tests. Status: 'synced' (idle, nothing pending) / 'saving' (in flight
   or retrying). Order is preserved (FIFO), so replayed server state matches the client. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SyncQueue = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function SyncQueue(opts) {
    opts = opts || {};
    this._fetch = opts.fetch || (typeof fetch !== "undefined" ? fetch.bind(null) : null);
    this._sleep = opts.sleep || function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
    this._base = opts.baseDelay || 300;      // backoff base (ms)
    this._max = opts.maxDelay || 8000;       // backoff ceiling (ms)
    this._maxAttempts = opts.maxAttempts || Infinity;
    this._onStatus = opts.onStatus || function () { };
    this.q = [];
    this._running = false;
    this.status = "synced";
  }

  SyncQueue.prototype._setStatus = function (s) {
    if (s !== this.status) { this.status = s; this._onStatus(s); }
  };

  // enqueue a write; returns a promise that resolves when THIS item finally lands
  SyncQueue.prototype.push = function (item) {
    var self = this;
    return new Promise(function (resolve, reject) {
      self.q.push({ item: item, resolve: resolve, reject: reject });
      self._pump();
    });
  };

  SyncQueue.prototype.pending = function () { return this.q.length; };

  SyncQueue.prototype._pump = function () {
    if (this._running) return;
    this._running = true;
    var self = this;
    (async function loop() {
      while (self.q.length) {
        self._setStatus("saving");
        var head = self.q[0];
        var attempt = 0;
        while (true) {
          attempt++;
          try {
            var res = await self._post(head.item);
            self.q.shift();
            head.resolve(res);
            break;
          } catch (e) {
            if (attempt >= self._maxAttempts) {   // give up on this item (won't block forever)
              self.q.shift();
              head.reject(e);
              break;
            }
            var delay = Math.min(self._max, self._base * Math.pow(2, attempt - 1));
            await self._sleep(delay);              // exponential backoff, then retry same item
          }
        }
      }
      self._running = false;
      self._setStatus("synced");
    })();
  };

  SyncQueue.prototype._post = async function (item) {
    var r = await this._fetch(item.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item.body || {})
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r;
  };

  return SyncQueue;
});
