// Shared web_companion client core.  Polling loop, composer, submit, finish.
(function () {
  const BASE = (() => {
    const p = window.location.pathname;
    return p.endsWith("/") ? p : p + "/";
  })();

  const pollIntervalMs = 1000;
  let lastVersions = {};
  let onPollDelta = () => {};
  let pollTimer = null;

  // ── Write capability ──────────────────────────────────────────────────
  // Reads need nothing. Writes need either a loopback connection (which the
  // server recognises on its own) or this token. It arrives in the URL
  // fragment, which browsers never send to the server and never write to
  // logs or Referer headers — so the owner URL can be pasted into a terminal
  // or a note without the credential leaking through the request path.
  //
  // Held in sessionStorage, not localStorage: a shared or borrowed device
  // forgets it when the tab closes.
  const TOKEN_HEADER = "X-WebCompanion-Token";
  const TOKEN_KEY = "webcompanion.token." + window.location.host;

  const token = (() => {
    const m = /(?:^|[#&])k=([^&]+)/.exec(window.location.hash || "");
    if (m) {
      const t = decodeURIComponent(m[1]);
      try { sessionStorage.setItem(TOKEN_KEY, t); } catch (_) {}
      // Strip it from the address bar so a screenshot or a shoulder-surfer
      // does not carry write access away. Same document, no reload.
      try {
        history.replaceState(null, "", window.location.pathname + window.location.search);
      } catch (_) {}
      return t;
    }
    try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; }
  })();

  function writeHeaders(extra) {
    const h = Object.assign({}, extra || {});
    if (token) h[TOKEN_HEADER] = token;
    return h;
  }

  let writable = false;

  const api = {
    BASE,
    get writable() { return writable; },
    async fetchJSON(path, opts) {
      const r = await fetch(BASE + path, opts || {});
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return await r.json();
    },
    async fetchText(path) {
      const r = await fetch(BASE + path);
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return await r.text();
    },
    async submit(payload) {
      const r = await fetch(BASE + "api/submit", {
        method: "POST", headers: writeHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error("submit failed: " + r.status);
      return await r.json();
    },
    async finish() {
      const r = await fetch(BASE + "api/finish", { method: "POST", headers: writeHeaders() });
      return r.ok;
    },
    async cancel() {
      const r = await fetch(BASE + "api/cancel", { method: "POST", headers: writeHeaders() });
      return r.ok;
    },
    async pasteImage(blob) {
      const r = await fetch(BASE + "api/upload", {
        method: "POST",
        headers: writeHeaders({ "Content-Type": blob.type || "image/png" }),
        body: blob,
      });
      if (!r.ok) throw new Error("upload failed: " + r.status);
      return await r.json();
    },
  };

  // Ask the server rather than inferring from the hostname: loopback grants
  // write access with no token at all, and only the server knows whether the
  // token we hold is the current one (it is reminted on every restart).
  //
  // "Could not ask" is not "was refused". Every open page holds one long-lived
  // connection and a browser allows six per origin, so the seventh request on
  // that origin queues behind connections that never end; a restarting server
  // or a waking laptop drops it a different way. None of that says anything
  // about what this client may do, and answering it with `read-only` renders
  // the document with every control silently removed — a page that looks fine
  // and does nothing, with no way back but a reload. So only an answer counts
  // as a verdict, and the rest is asked again.
  //
  // This is the same fix, and the same reasoning, as the daemon's own core.js
  // (webcompanion, src/webcompanion/static/core.js). Nothing launches THIS
  // engine any more — every skill pushes to the daemon — so it is carried
  // here only so the two copies do not disagree if it is ever revived.
  const PROBE_TIMEOUT_MS = 4000;
  const PROBE_RETRY_MS = [1000, 2000, 5000, 10000];

  async function probeWritable() {
    const ctl = typeof AbortController === "function" ? new AbortController() : null;
    const timer = ctl ? setTimeout(() => ctl.abort(), PROBE_TIMEOUT_MS) : null;
    try {
      const opts = { headers: writeHeaders() };
      if (ctl) opts.signal = ctl.signal;
      const r = await fetch("/api/whoami", opts);
      if (r.ok) return !!(await r.json()).writable;
      return (r.status === 401 || r.status === 403 || r.status === 404) ? false : null;
    } catch (_) {
      return null;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  async function resolveWritable() {
    for (let attempt = 0; ; attempt++) {
      const verdict = await probeWritable();
      if (verdict !== null) {
        writable = verdict;
        document.body.classList.toggle("read-only", !writable);
        return writable;
      }
      const wait = PROBE_RETRY_MS[Math.min(attempt, PROBE_RETRY_MS.length - 1)];
      await new Promise((r) => setTimeout(r, wait));
    }
  }

  async function pollOnce() {
    try {
      const data = await api.fetchJSON("poll");
      if (data.finished) {
        document.body.classList.add("session-finished");
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      }
      onPollDelta(data, lastVersions);
      lastVersions = { ...(data.blocks || {}), ...(data.threads || {}) };
    } catch (e) {
      console.warn("poll failed", e);
    }
  }

  function startPolling() {
    pollOnce();
    pollTimer = setInterval(pollOnce, pollIntervalMs);
  }

  window.WebCompanion = {
    api,
    get writable() { return writable; },
    resolveWritable,
    init({ onPollDelta: handler }) {
      onPollDelta = handler || (() => {});
      // Paint read-only before the first render so a reader never sees
      // controls appear and then vanish. Polling does not wait on it —
      // reading is what a shared link is for.
      resolveWritable();
      startPolling();
    },
  };
})();
