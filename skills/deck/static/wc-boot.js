/* wc-boot.js — the page loader every skill's entry.js shares.
 *
 * Canonical source: skills/_shared/static/wc-boot.js. Each skill that uses it
 * carries a byte-identical copy in its own static/ (the daemon serves a page
 * from that one directory); skills/tests/test_shared_static_copies.py fails
 * on a copy that drifts. Edit the canonical file, then copy it over.
 *
 * An ES module: entry.js is loaded by the daemon's shell as a module, imports
 * this beside it, and hands over its own import.meta.url so every asset
 * resolves against the asset directory rather than the document. A runtime
 * <script src="x.js"> resolves against the page's URL (/s/<sid>/x.js), not
 * the asset route (/s/<sid>/assets/x.js), and 404s.
 *
 * Scripts are inserted with async = false. For a script inserted at runtime
 * that is what keeps execution in insertion order: every such script joins
 * one ordered list and runs as soon as it and everything before it have
 * loaded, while all of them download at once. (`defer` gives that guarantee
 * only to tags present when the page is parsed.) So a page inserts its whole
 * list in one go with loadScripts() and still gets the order it wrote.
 */

export function loader(importMetaUrl) {
  const base = new URL("./", importMetaUrl);
  const asset = (name) => new URL(name, base).href;

  // Replaces the page with one line of text: a page that cannot load says so
  // rather than staying blank.
  function fail(message) {
    document.body.innerHTML = '<main class="waiting"><p></p></main>';
    document.body.querySelector("p").textContent = message;
  }

  // Resolves either way: a missing stylesheet is a cosmetic failure, and
  // hanging the whole boot on it would turn it into a blank page.
  function loadStylesheet(name) {
    return new Promise((resolve) => {
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = asset(name);
      l.onload = l.onerror = () => resolve();
      document.head.appendChild(l);
    });
  }

  function insertScript(name) {
    const s = document.createElement("script");
    s.src = asset(name);
    s.async = false;
    const done = new Promise((resolve, reject) => {
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("failed to load " + name));
    });
    document.body.appendChild(s);
    return done;
  }

  // One script; rejects if it fails to load.
  function loadScript(name) {
    return insertScript(name);
  }

  // A list of scripts, all inserted now so they download in parallel, run in
  // list order. Resolves to one promise per script, in the same order, so a
  // caller can wait for any one of them; a script that fails to load does not
  // stop the ones after it from running.
  function loadScripts(names) {
    return names.map(insertScript);
  }

  return { asset, fail, loadStylesheet, loadScript, loadScripts };
}
