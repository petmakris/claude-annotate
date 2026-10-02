/* entry.js — dataflow's registered asset entry point.
   Loads markdown-it.min.js, then wc-threads.js, then dataflow.js, in that
   strict order: dataflow.js reads `window.markdownit` at module-load time to
   build its `MD` renderer, so markdown-it must exist before dataflow.js
   starts, and it also calls WcThreads.derive() as soon as it runs, so
   wc-threads.js must not start after it either. Mirrors annotate/static/
   entry.js's own reason for existing — the daemon serves a session's
   renderer from exactly one directory, so anything a skill's page needs
   beyond its own top-level script has to be loaded here, in order, rather
   than declared as separate <script> tags in a <head> that dataflow's page
   never gets to author (the daemon writes the shell).
*/
(function () {
  "use strict";
  // A script tag inserted at runtime resolves a relative `src` against the
  // document's own URL, not against this module's — so a bare "dataflow.js"
  // would ask the daemon for `/s/<sid>/dataflow.js` (a sibling of the shell
  // page) instead of `/s/<sid>/assets/dataflow.js`, where the asset actually
  // lives, and 404. Resolving against `import.meta.url` (this file's own
  // absolute URL, since the shell loads it as a module) is the fix annotate's
  // own entry.js already uses for the same reason.
  const base = new URL("./", import.meta.url);
  const asset = (name) => new URL(name, base).href;

  function fail(message) {
    document.body.innerHTML =
      '<main class="waiting"><p></p></main>';
    document.body.querySelector("p").textContent = message;
  }
  function loadStylesheet(href) {
    return new Promise((resolve) => {
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = href;
      // Resolve either way: a missing stylesheet is a cosmetic failure, and
      // hanging the whole boot on it would turn it into a blank page.
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

  // The daemon's shell page is a bare `<main data-wc-root></main>` — it never
  // printed `dataflow.css` or the `#app` container the way `server.py`'s own
  // `_shell()` used to. Both are this file's job now, and both must exist
  // before `dataflow.js` runs its first `render()`.
  const root = document.querySelector("[data-wc-root]") || document.body;
  root.innerHTML = '<div id="app"></div>';

  loadStylesheet(asset("dataflow.css"));
  loadScript(asset("markdown-it.min.js"))
    .then(() => loadScript(asset("wc-threads.js")))
    .then(() => loadScript(asset("dataflow.js")))
    .catch((e) => {
      fail("This page failed to load: " + e.message);
    });
})();
