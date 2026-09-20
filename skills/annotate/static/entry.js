// The renderer the webcompanion daemon loads for an annotate session.
//
// The daemon serves a bare shell page — a title, its own core.js, and one
// module tag pointing here — and knows nothing about annotation. So this file
// does what annotate's own server used to do at request time: paint the page
// frame, pull in the stylesheets and scripts, and only then let the page code
// run.
//
// Order is the whole job. Four things must happen in sequence, and every one
// of them used to be guaranteed by the order of tags in a server-printed
// <head>:
//
//   1. the shell markup exists, because script.js queries for it on load
//   2. compat.js has replaced window.WebCompanion, because script.js calls it
//   3. highlight.js and markdown-it exist, because script.js builds a
//      markdown-it instance with the highlight hook at module scope
//   4. script.js has run, because maximize.js mounts into what it builds
import { SHELL_HTML } from "./shell.js";

const CSS = ["core.css", "style.css", "diagram.css", "popover.css", "code-theme.css"];

// Same order the old server's <head> had, and for the same reasons: the
// highlighter and the markdown renderer before script.js builds its instance;
// diff.js before the first acked round can read it; maximize.js near the end,
// because it mounts into DOM script.js creates. fullscreen.js only needs the
// button shell.js already rendered, so its position after that is not load
// bearing — it sits last because nothing else depends on it.
const JS = [
  "popover.js",
  // Before script.js: it calls blockTitle at module scope the first time a
  // card is painted, and the rule lives here.
  "block-title.js",
  "highlight.min.js",
  "markdown-it.min.js",
  "diff.js",
  "script.js",
  "export.js",
  "subunits.js",
  "highlighter.js",
  "fuse.min.js",
  "search.js",
  "voice.js",
  "maximize.js",
  "fullscreen.js",
];

function addStylesheet(href) {
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

// Appended one at a time and awaited, not emitted as a batch of `defer` tags.
// `defer` preserves document order only for tags present at parse time; these
// are injected after parsing, where the guarantee does not hold and the order
// above is load-order roulette.
function addScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.async = false;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("failed to load " + src));
    document.body.appendChild(s);
  });
}

function fail(message) {
  document.body.innerHTML =
    '<main class="waiting"><p></p></main>';
  document.body.querySelector("p").textContent = message;
}

async function boot() {
  const base = new URL("./", import.meta.url);
  const asset = (name) => new URL(name, base).href;

  // The document's own identity, which the old server interpolated into the
  // page it printed. Read it first: a page that paints its frame before it
  // knows whether there is anything to show flashes an empty header.
  let doc = {};
  try {
    const r = await fetch("items/__doc__", { cache: "no-store" });
    if (r.ok) doc = (await r.json()).body || {};
  } catch (_) {
    /* fall through to the waiting state below */
  }

  await Promise.all(CSS.map((f) => addStylesheet(asset(f))));

  if (!doc.order || !doc.order.length) {
    fail("Waiting for a response.");
    return;
  }

  document.body.innerHTML = SHELL_HTML;
  document.body.dataset.responseId = doc.response_id || "";
  const title = doc.title || "Response";
  document.title = title;
  document.getElementById("hdr-title").textContent = title;
  document.getElementById("hdr-respid").textContent = doc.response_id || "";

  // The repo root gates the "open this in my editor" control. Only an owner
  // gets it: the read-only share link is allowed to serve code excerpts, but
  // that decision never covered handing a stranger the server's own directory
  // layout — and the control it enables would be refused for them anyway.
  //
  // Deliberately NOT awaited. It used to be, and that put one optional
  // control's permission check across the critical path of the whole page:
  // every open document holds an SSE stream, a browser allows six
  // connections per origin, and a request that cannot get one waits without
  // ever failing. Boot stopped here — no compat.js, no script.js, so no
  // hover controls and no way to comment on anything — while the document
  // above it rendered perfectly and looked like it was simply ignoring the
  // pointer. Nothing below this line needs the answer, so nothing waits for
  // it; the control appears if and when it arrives.
  fetch("/api/whoami", { cache: "no-store" })
    .then((who) => (who.ok ? who.json() : null))
    .then((me) => {
      if (me && me.writable && doc.cwd) document.body.dataset.repoRoot = doc.cwd;
    })
    .catch(() => { /* no control, which is the safe direction */ });

  await addScript(asset("compat.js"));
  for (const f of JS) {
    try {
      await addScript(asset(f));
    } catch (e) {
      console.error(e);
    }
  }
}

boot().catch((e) => {
  console.error(e);
  fail("This page failed to load: " + e.message);
});
