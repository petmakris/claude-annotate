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
  async function resolveWritable() {
    try {
      const r = await fetch("/api/whoami", { headers: writeHeaders() });
      writable = r.ok ? !!(await r.json()).writable : false;
    } catch (_) {
      writable = false;
    }
    document.body.classList.toggle("read-only", !writable);
    return writable;
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
