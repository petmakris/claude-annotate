// The stage: one tab and one pane per named view, each kept live against its source.
const LIBS = [
  "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js",
  "https://cdn.jsdelivr.net/npm/marked@12/marked.min.js",
  "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js",
];
const loadScript = (src) => new Promise((ok) => {
  const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = ok; document.head.append(s);
});
await Promise.all(LIBS.map(loadScript));

const WC = window.WebCompanion;
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
// Imported lazily, only when a diagram view actually renders: a jsDelivr outage must not
// block the whole page behind a library nothing on this stage may need.
let mermaidReady = false;

const root = document.querySelector("[data-wc-root]") || document.body;
root.innerHTML = `<div class="stage">
  <nav class="tabs" role="tablist" aria-label="Stage"></nav>
  <div class="panes"><p class="empty">Nothing on the stage yet. Views appear here as Claude shows them.</p></div>
</div>`;
const tabsEl = root.querySelector(".tabs"), panesEl = root.querySelector(".panes");
const views = new Map();            // name -> {body, tab, pane}
let layout = { order: [], front: null };
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function frameUrl(src, rev, hash) {
  if (src.type === "file") {
    const file = src.file.split("/").map(encodeURIComponent).join("/");
    return `${WC.api.BASE}mounts/${encodeURIComponent(src.mount)}/${file}?rev=${rev}` +
      (hash || (src.fragment ? "#" + src.fragment : ""));
  }
  if (src.type === "session") return `/s/${encodeURIComponent(src.sid)}/`;
  return src.url;
}

function where(src) {
  if (src.type === "file") return src.path;
  if (src.type === "url") return src.url;
  if (src.type === "session") return `${src.kind} · ${src.slug}`;
  if (src.format === "code") return `${src.path}:${src.start}-${src.start + src.lines.length - 1}`;
  return src.format;
}

async function renderInline(src) {
  const box = document.createElement("div");
  if (src.format === "code") {
    box.className = "code";
    const [ha, hb] = src.highlight || [0, -1];
    src.lines.forEach((line, i) => {
      const n = src.start + i, row = document.createElement("div");
      row.className = "ln" + (n >= ha && n <= hb ? " hl" : "");
      let html;
      try {
        const lang = window.hljs?.getLanguage(src.lang) ? src.lang : "plaintext";
        html = window.hljs.highlight(line, { language: lang, ignoreIllegals: true }).value;
      } catch { html = esc(line); }
      row.innerHTML = `<i>${n}</i><span>${html || " "}</span>`;
      box.append(row);
    });
  } else if (src.format === "diagram") {
    box.className = "diagram";
    const id = "m" + Math.random().toString(36).slice(2);
    try {
      const mermaid = (await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")).default;
      if (!mermaidReady) {
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral" });
        mermaidReady = true;
      }
      box.innerHTML = (await mermaid.render(id, src.body)).svg;
    } catch { document.getElementById("d" + id)?.remove(); box.innerHTML = `<pre>${esc(src.body)}</pre>`; }
  } else {
    box.className = "tablewrap";
    box.innerHTML = window.marked && window.DOMPurify
      ? DOMPurify.sanitize(marked.parse(src.body), { FORBID_TAGS: ["form", "meta", "iframe", "style", "base"] })
      : `<pre>${esc(src.body)}</pre>`;
  }
  return box;
}

async function fillPane(v) {
  const { source: src, rev, title } = v.body;
  v.pane.innerHTML = `<header><span class="where"></span><a class="open" target="_blank" rel="noopener" hidden>Open ↗</a></header>`;
  v.pane.querySelector(".where").textContent = where(src);
  if (src.type === "inline") { v.pane.append(await renderInline(src)); return; }
  if (src.type === "file" && src.missing) {
    const p = document.createElement("p"); p.className = "waiting";
    p.textContent = `Waiting for ${src.path}`; v.pane.append(p); return;
  }
  const open = v.pane.querySelector(".open");
  open.href = frameUrl(src, rev); open.hidden = false;
  const frame = document.createElement("iframe");
  frame.className = "frame"; frame.title = title; frame.src = frameUrl(src, rev);
  v.pane.append(frame);
}

function reloadFrame(v) {
  const frame = v.pane.querySelector("iframe.frame");
  if (!frame) return fillPane(v);
  let hash = "", x = 0, y = 0;
  try { const w = frame.contentWindow; hash = w.location.hash; x = w.scrollX; y = w.scrollY; } catch {}
  frame.addEventListener("load", () => { try { frame.contentWindow.scrollTo(x, y); } catch {} }, { once: true });
  frame.src = frameUrl(v.body.source, v.body.rev, hash);
}

function select(name) {
  for (const [n, v] of views) {
    v.tab.setAttribute("aria-selected", String(n === name));
    v.pane.hidden = n !== name;
  }
}

function reorderTabs() {
  const names = layout.order.filter((n) => views.has(n));
  for (const n of views.keys()) if (!names.includes(n)) names.push(n);
  for (const n of names) { tabsEl.append(views.get(n).tab); }
  panesEl.querySelector(".empty")?.toggleAttribute("hidden", views.size > 0);
  return names;
}

function selectedName() {
  for (const [n, v] of views) if (v.tab.getAttribute("aria-selected") === "true") return n;
  return null;
}

// A __layout__ change (and the initial render) is the only thing allowed to move the
// visible tab to the front.
function applyLayout() {
  const names = reorderTabs();
  select(views.has(layout.front) ? layout.front : names[names.length - 1]);
}

// A view upserting or disappearing only reorders tabs; it must never pull the viewer away
// from what they're reading unless nothing was selected, or the selected view is the one
// that just vanished.
function afterViewChange(removedName) {
  const names = reorderTabs();
  const sel = selectedName();
  if (!sel || sel === removedName) select(views.has(layout.front) ? layout.front : names[names.length - 1]);
}

async function upsert(body) {
  let v = views.get(body.name);
  if (!v) {
    const tab = document.createElement("button");
    tab.setAttribute("role", "tab"); tab.dataset.view = body.name;
    tab.onclick = () => select(body.name);
    const pane = document.createElement("section");
    pane.className = "pane"; pane.dataset.view = body.name; pane.hidden = true;
    panesEl.append(pane);
    v = { body, tab, pane };
    views.set(body.name, v);
    tab.textContent = body.title;
    await fillPane(v);
    // The daemon lists __layout__ before the view it names, so a newly shown view arrives
    // after the layout that fronts it: bring it forward now. Only on creation — an update to
    // a view that already exists never moves the selection.
    if (body.name === layout.front) select(body.name);
    return;
  }
  const before = v.body;
  v.body = body;
  v.tab.textContent = body.title;
  const { missing: m1, ...s1 } = before.source, { missing: m2, ...s2 } = body.source;
  if (same(s1, s2) && m1 === m2 && before.rev !== body.rev && body.source.type !== "inline") reloadFrame(v);
  else if (!same(before.source, body.source) || before.title !== body.title) await fillPane(v);
}

function remove(name) {
  const v = views.get(name); if (!v) return;
  v.tab.remove(); v.pane.remove(); views.delete(name);
}

async function onItem(anchor, version) {
  versions.set(anchor, version);
  if (anchor === "__layout__") {
    if (version) layout = (await WC.api.fetchJSON("items/__layout__")).body;
    return applyLayout();
  }
  if (!anchor.startsWith("view:")) return;
  if (!version) {
    const name = anchor.slice(5);
    remove(name);
    return afterViewChange(name);
  }
  const item = await WC.api.fetchJSON("items/" + encodeURIComponent(anchor));
  await upsert(item.body);
  afterViewChange();
}

// WC.init runs before the snapshot fetch so nothing that changes during load is missed: its
// opening burst replays every anchor's current state with each delta marked initial:true, and
// a client that already has that state from its own fetch may skip a burst delta whose version
// matches what it already has — but only once it knows what that version is. Until the
// snapshot has rendered we don't, so every delta that lands first goes into `buffered` instead
// of being dropped; once the snapshot is in, we replay `buffered` and only then does `queue`
// exist, so a delta that arrives afterwards joins the same ordered chain a reload can't race.
const versions = new Map();   // anchor -> version already reflected on the page
let queue = null;
let failed = false;           // the snapshot never loaded: drop deltas rather than buffer them forever
const buffered = [];
const alreadyReflected = (d) => d.initial && versions.has(d.anchor) && versions.get(d.anchor) === d.version;

function schedule(anchor, version) {
  queue = queue.then(() => onItem(anchor, version)).catch((e) => console.warn("stage:", e));
}

WC.init({
  onDelta(d) {
    if (d.kind !== "item" || failed) return;
    if (!queue) { buffered.push(d); return; }
    if (alreadyReflected(d)) return;
    schedule(d.anchor, d.version);
  },
});

let snapshot = null;
try {
  snapshot = await WC.api.fetchJSON("items");
} catch (e) {
  failed = true;
  buffered.length = 0;
  const line = panesEl.querySelector(".empty");
  line.classList.add("failed");
  line.textContent = `Could not load the stage: ${e?.message || e}. Reload to retry.`;
}

if (snapshot) {
  for (const [anchor, item] of Object.entries(snapshot)) {
    versions.set(anchor, item.version);
    if (anchor.startsWith("view:")) await upsert(item.body);
    if (anchor === "__layout__") layout = item.body;
  }
  applyLayout();

  queue = Promise.resolve();
  for (const d of buffered) {
    if (alreadyReflected(d)) continue;
    schedule(d.anchor, d.version);
  }
}
