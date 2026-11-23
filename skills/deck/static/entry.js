/* entry.js — deck's registered asset entry point.
   Loads core.css, then deck.css, then deck.js, in that order, through
   wc-boot.js (a copy of skills/_shared/static/wc-boot.js). The daemon
   serves a session's renderer from exactly one directory, so anything
   deck's page needs beyond its own top-level script is loaded here.

   deck.js never builds its own markup — it reaches straight for
   `#app`/`#deckhead`/`#deckbody` with `document.getElementById`, on the
   assumption that the page shell already put them there. The daemon's shell page is a bare `<main data-wc-root></main>`,
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
import { loader } from "./wc-boot.js";

const { fail, loadStylesheet, loadScript } = loader(import.meta.url);

const root = document.querySelector("[data-wc-root]") || document.body;
root.innerHTML = '<div id="app"><div id="deckhead"></div><div id="deckbody"></div></div>';

loadStylesheet("core.css")
  .then(() => loadStylesheet("deck.css"))
  .then(() => loadScript("deck.js"))
  .catch((e) => fail("This page failed to load: " + e.message));
