// skills/annotate/static/speech-client.js
/* The page's side of the daemon's speech routes (Plan 1).
 *
 * The routes live at the site root, not under the session, so they are called
 * with fetch directly rather than through WebCompanion.api (whose paths are
 * session-relative). The headers are the ones core.js sends: the contract
 * number, and the owner token from sessionStorage when the page was opened
 * through an owner URL. Keep the two in step if core.js's ever change.
 *
 * Azure's browser SDK is 378 KB, so it is loaded the first time something
 * speaks or listens, never at page load.
 */
(function () {
  "use strict";

  const BASE = new URL("./", document.currentScript ? document.currentScript.src : location.href);
  const SDK_SRC = new URL("vendor/speech-sdk.min.js", BASE).href;
  const CONTRACT = "1";
  const TOKEN_KEY = "webcompanion.token." + location.host;

  function headers(extra) {
    const h = Object.assign({ "X-WebCompanion-Contract": CONTRACT }, extra || {});
    try { const t = sessionStorage.getItem(TOKEN_KEY); if (t) h["X-WebCompanion-Token"] = t; } catch (_) {}
    return h;
  }

  async function call(method, path, body) {
    const opts = { method, headers: headers(body ? { "Content-Type": "application/json" } : null) };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) {
      const e = new Error((await r.text()).trim() || `HTTP ${r.status}`);
      e.status = r.status;
      throw e;
    }
    return r.json();
  }

  // Only a configured answer is kept, for a minute: a reader who sets Azure
  // up after the page loaded should not have to reload to be heard. Two
  // first calls at once share one request; a failed one is not remembered.
  let statusCache = null, statusAt = 0, statusPending = null;
  function status() {
    if (statusCache && Date.now() - statusAt < 60000) return Promise.resolve(statusCache);
    if (!statusPending) {
      statusPending = call("GET", "/api/speech/status").then((s) => {
        statusPending = null;
        if (s && s.configured) { statusCache = s; statusAt = Date.now(); }
        else statusCache = null;
        return s;
      }, (e) => { statusPending = null; throw e; });
    }
    return statusPending;
  }

  let tok = null, tokUntil = 0, tokPending = null;
  // `minValidMs` asks for a token with at least that long left, so a session
  // that is already running can be handed a new one before the old one dies.
  function token(minValidMs) {
    if (tok && Date.now() + (minValidMs || 0) < tokUntil) return Promise.resolve(tok);
    if (!tokPending) {
      tokPending = call("POST", "/api/speech/token").then((t) => {
        tokPending = null;
        tok = { token: t.token, region: t.region };
        tokUntil = Date.now() + (t.expires_in || 540) * 1000;
        return tok;
      }, (e) => { tokPending = null; throw e; });
    }
    return tokPending;
  }

  const scripts = new Map();
  function script(req) {
    const key = JSON.stringify(req);
    if (!scripts.has(key)) {
      const p = call("POST", "/api/speech/script", req);
      scripts.set(key, p);
      p.catch(() => scripts.delete(key));      // a failure is not remembered
    }
    return scripts.get(key);
  }

  let sdk = null;
  function loadSdk() {
    if (window.SpeechSDK) return Promise.resolve(window.SpeechSDK);
    if (!sdk) {
      sdk = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = SDK_SRC;
        // Either way it failed, the tag goes and the next call tries afresh.
        const fail = (msg) => { sdk = null; s.remove(); reject(new Error(msg)); };
        s.onload = () => window.SpeechSDK ? resolve(window.SpeechSDK)
          : fail("The speech engine loaded but did not start");
        s.onerror = () => fail("The speech engine could not load");
        document.head.appendChild(s);
      });
    }
    return sdk;
  }

  function pageContext(section) {
    const root = window.AnnotateAnchors?.contentOf(section);
    const context = root ? window.AnnotateAnchors.textOf(root).slice(0, 4000) : "";
    const glossary = window.AnnotateGlossary?.terms ? window.AnnotateGlossary.terms() : [];
    const title = document.querySelector(".header-text")?.textContent?.trim() || document.title || "";
    return { context, glossary, page_title: title };
  }

  window.AnnotateSpeechClient = { status, token, script, loadSdk, pageContext };
})();
