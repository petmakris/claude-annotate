/* entry.js — dataflow's registered asset entry point.
   Loads markdown-it.min.js, wc-threads.js and wc-open.js, then dataflow.js,
   in that strict order: dataflow.js reads `window.markdownit` at module-load
   time to build its `MD` renderer, so markdown-it must exist before
   dataflow.js starts, and it also calls WcThreads.derive() as soon as it
   runs, so wc-threads.js must not start after it either. The daemon serves a
   session's renderer from exactly one directory, so anything a skill's page
   needs beyond its own top-level script has to be loaded here, in order,
   rather than declared as separate <script> tags in a <head> that dataflow's
   page never gets to author (the daemon writes the shell).

   wc-boot.js (a copy of skills/_shared/static/wc-boot.js) inserts the list in
   one go — the four download in parallel and still run in this order.
*/
import { loader } from "./wc-boot.js";

const { fail, loadStylesheet, loadScripts } = loader(import.meta.url);

// The daemon's shell page is a bare `<main data-wc-root></main>` — it never
// printed `dataflow.css` or the `#app` container the way `server.py`'s own
// `_shell()` used to. Both are this file's job now, and both must exist
// before `dataflow.js` runs its first `render()`.
const root = document.querySelector("[data-wc-root]") || document.body;
root.innerHTML = '<div id="app"></div>';

loadStylesheet("dataflow.css");
Promise.all(loadScripts(["markdown-it.min.js", "wc-threads.js", "wc-open.js", "dataflow.js"]))
  .catch((e) => {
    fail("This page failed to load: " + e.message);
  });
