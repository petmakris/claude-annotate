/* entry.js — deck's registered asset entry point.
   Loads core.css, then deck.css, then deck.js, in that order. Mirrors
   dataflow/static/entry.js's own loader-stub role (Phase 1) — the daemon
   serves a session's renderer from exactly one directory, so anything
   deck's page needs beyond its own top-level script is loaded here.

   deck.js never builds its own markup — it reaches straight for
   `#app`/`#deckhead`/`#deckbody` with `document.getElementById`, on the
   assumption that the old server.py's `_page()` shell already put them
   there. The daemon's shell page is a bare `<main data-wc-root></main>`,
   so this file has to inject that markup itself before deck.js runs, the
   same fix dataflow/static/entry.js already applies for its own `#app`.

   core.css IS loaded here, before deck.css: deck.css uses --surface,
   --border, --text, --text-strong, --text-dim, --accent and --hover-tint
   without ever declaring them itself — they only exist under core.css's
   :root. Without it every `var(--x)` in deck.css is invalid at computed-
   value time, which drops the whole declaration silently (no border, no
   text color) rather than erroring, so this was verified by reading both
   stylesheets side by side, not by opening the page and noticing a crash.
*/
(function () {
  "use strict";
  const base = new URL("./", import.meta.url);
  const asset = (name) => new URL(name, base).href;

  function fail(message) {
    document.body.innerHTML = '<main class="waiting"><p></p></main>';
    document.body.querySelector("p").textContent = message;
  }
  function loadStylesheet(href) {
    return new Promise((resolve) => {
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = href;
      l.onload = l.onerror = () => resolve();
      document.head.appendChild(l);
    });
  }
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("failed to load " + src));
      document.body.appendChild(s);
    });
  }

  const root = document.querySelector("[data-wc-root]") || document.body;
  root.innerHTML = '<div id="app"><div id="deckhead"></div><div id="deckbody"></div></div>';

  loadStylesheet(asset("core.css"))
    .then(() => loadStylesheet(asset("deck.css")))
    .then(() => loadScript(asset("deck.js")))
    .catch((e) => fail("This page failed to load: " + e.message));
})();
