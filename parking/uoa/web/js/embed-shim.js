/* STAND embed shim: lets the map run when WordPress embeds it.

   WordPress shows a page from a site it does not know inside an iframe sandboxed with
   "allow-scripts" only. That gives the page an opaque origin. MapLibre's web workers then
   start at a blob:null address, and MapLibre's message code drops every message whose
   sender reports a different location.origin: "null" in the worker, but
   https://span.tfwelch.com in the page. No map layer would ever load.

   This wraps Worker so each side sees the origin it expects. Outside such a sandbox (a
   normal visit, a same-origin frame, or a file opened from disk) it does nothing.
   Load it before MapLibre creates its workers, i.e. before js/app.js. */
(() => {
  "use strict";
  // (a file opened from disk reports location.origin "file://", which MapLibre already accepts: leave it alone)
  if (typeof Worker !== "function" || self.origin !== "null" || location.origin === "null" || location.protocol === "file:") return;
  const Native = Worker;
  const here = location.origin;
  const isObj = (d) => d !== null && typeof d === "object";
  const toWorker = (m) => (isObj(m) && m.origin === here ? Object.assign({}, m, { origin: "null" }) : m);
  const fromWorker = (e) => (isObj(e.data) && e.data.origin === "null" ? new MessageEvent("message", { data: Object.assign({}, e.data, { origin: here }) }) : e);
  const wrapped = new WeakMap();

  class EmbedWorker extends Native {
    postMessage(message, transfer) {
      return transfer === undefined ? super.postMessage(toWorker(message)) : super.postMessage(toWorker(message), transfer);
    }
    addEventListener(type, listener, options) {
      if (type !== "message" || typeof listener !== "function") return super.addEventListener(type, listener, options);
      let w = wrapped.get(listener);
      if (!w) { w = (e) => listener.call(this, fromWorker(e)); wrapped.set(listener, w); }
      return super.addEventListener(type, w, options);
    }
    removeEventListener(type, listener, options) {
      return super.removeEventListener(type, (type === "message" && wrapped.get(listener)) || listener, options);
    }
  }
  window.Worker = EmbedWorker;
})();
