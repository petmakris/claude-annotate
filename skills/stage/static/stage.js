// The stage: one tab and one pane per named view, each kept live against its source.
//
// It paints at once: the shell, the snapshot and every view go up before any library has
// loaded. The libraries ship beside this file (vendor/, see VERSIONS.txt) and upgrade what is
// already on screen when they arrive; mermaid is large, so it loads on demand, and a diagram
// draws in its own task so a slow load never holds up other views.
//
// Each pane is a header (title, plain-words meta, buttons) over a body that scrolls; tables,
// code and diagrams scroll inside their own boxes so the header and a table's column names
// stay in view.
//
// Embedded in a talk call, the stage and the call page talk over postMessage. The stage reads only
// messages from its parent window, and only when it has one; a stage opened on its own ignores them all.
//   Talk to stage:
//     {type:'stage:front', view, manual, answer}  bring a view to the front: when following is on, or
//                                         always when manual (a chip was pressed). A chip works as a tab tap:
//                                         another board opens whole and following turns off; the board already
//                                         in front stays as it is. Fronted by the voice of an answer with no
//                                         scene of its own for the view, the view shows whole. A view not here
//                                         yet is fronted when it arrives, unless another front came first
//     {type:'stage:point', view, target}  when following: front the view and light up part of it.
//                                         target {type:'lines', a, b} | {type:'row', n} | {type:'row', text}
//                                         | {type:'node', id}; null clears every spot
//     {type:'stage:answer', n}            answer n started playing: following turns on again, and a frame
//                                         or front another answer sent for a view not here yet is dropped
//     {type:'stage:key', view, index}     key point number index (from 1) was just said: it gets the bar
//                                         and a short glow; the Key points tab is never fronted for it
//     {type:'stage:theme', theme}         'light' or 'dark', chosen on the call page
//     {type:'stage:zoom', zoom}           how large everything draws: 1 at a desk, more on a TV across the room
//     {type:'stage:follow', on}           the call page's switch turned following on or off
//     {type:'stage:frame', view, n, animate, answer}  show frame n of the scene answer number `answer` said
//                                         the view with (body.scenes[answer]; without an answer, body.scene),
//                                         clamped to its rest frame, animated only as the next one; never for
//                                         the view in front while following is off
//     {type:'stage:state', front, frames, keys, answer}  after a jump: every scene's frame as a snap, then the
//                                         front and the key point lit (0: none). It replaces the whole picture:
//                                         frames waiting for a view not here yet are dropped first
//   Stage to talk (to '*': nothing secret in them):
//     {type:'stage:ready'}                once, after the first render
//     {type:'stage:views', list:[{name, title, kind, answer}]}   after every change to the tabs
//     {type:'stage:changed', name, title, isNew}                 a view was created or its source changed
//     {type:'stage:follow', on}                                  following changed here (a tab tap, a chip, a step
//                                                                by hand, a new answer)
//     {type:'stage:shown', view}                                 this board is in front now, by the voice or by hand
//     {type:'stage:key', key}                                    Space, ArrowLeft or ArrowRight pressed here, on nothing
//                                                                that takes keys: the call page pauses or moves the answer
//     {type:'stage:missing', view}                               a chip asked for a view this stage does not hold
//     {type:'stage:keymiss', view, keys}                         keys of a scene its drawing does not hold; they stay shown
//   Stage to the page in a page board (to '*'), once the call page has set a theme:
//     {type:'stage:theme', theme}         on each load and each change. A page from this daemon (a file or
//                                         session board) also gets data-theme on its <html> straight away.
// Unknown types are ignored.
import { flowchartKeys, nodeElements } from "./svg_keys.js";
import { applyFrame, beingSaid, stepLabel } from "./scene.js";
import { layoutLanes, renderLanes } from "./lanes.js";
import { layoutMap, renderMap } from "./map.js";

const VENDOR = ["highlight.min.js", "marked.min.js", "purify.min.js"]
  .map((f) => new URL("vendor/" + f, import.meta.url).href);
const MERMAID = new URL("vendor/mermaid.min.js", import.meta.url).href;

const withTimeout = (p, ms) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error("timed out")), ms))]);
const loadScript = (src) => new Promise((ok, no) => {
  const s = document.createElement("script"); s.src = src;
  s.onload = ok; s.onerror = () => { s.remove(); no(new Error("could not load " + src)); };
  document.head.append(s);
});
const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 3000 }) : setTimeout(fn, 1500));

// Resolves even on error or timeout: rendering uses whatever arrived. Reset by 'Try again'.
let libsP = null;
function libsReady() {
  if (!libsP) {
    libsP = Promise.all(VENDOR.map((src) => withTimeout(loadScript(src), 8000)
      .catch((e) => console.warn("stage:", e.message)))).then(() => {});
  }
  return libsP;
}
const hasMarkdown = () => !!(window.marked && window.DOMPurify);

// ---- Theme: mermaid takes its colours from the shared tokens -------------------------------

// A token as an opaque hex colour: a translucent token is laid over --panel first, because
// mermaid derives its other shades from these and a node fill should not show the grid through.
function tokenHex(name) {
  const probe = document.createElement("i");
  probe.style.cssText = `position:absolute;visibility:hidden;color:var(${name});background:var(--panel)`;
  document.body.append(probe);
  const cs = getComputedStyle(probe), fg = rgba(cs.color), bg = rgba(cs.backgroundColor);
  probe.remove();
  const mix = fg.map((c, i) => (i < 3 ? Math.round(c * fg[3] + bg[i] * (1 - fg[3])) : 1));
  return "#" + mix.slice(0, 3).map((c) => c.toString(16).padStart(2, "0")).join("");
}
function rgba(s) {
  const n = (s.match(/[\d.]+/g) || [0, 0, 0]).map(Number);
  return [n[0], n[1], n[2], n.length > 3 ? n[3] : 1];
}

function mermaidConfig() {
  const t = (n) => tokenHex(n);
  return {
    startOnLoad: false, securityLevel: "strict", theme: "base", deterministicIds: true, htmlLabels: false,
    themeVariables: {
      fontFamily: "Geist, system-ui, sans-serif", fontSize: "15px",
      primaryColor: t("--panel"), primaryBorderColor: t("--acc"), primaryTextColor: t("--ink"),
      lineColor: t("--muted"), secondaryColor: t("--hl-soft"), tertiaryColor: t("--row-alt"),
      clusterBkg: t("--row-alt"), clusterBorder: t("--line"), edgeLabelBackground: t("--panel"),
      noteBkgColor: t("--claude-soft"), noteTextColor: t("--ink"), noteBorderColor: t("--line"),
      textColor: t("--ink"), mainBkg: t("--panel"), nodeBorder: t("--acc"), titleColor: t("--ink"),
    },
    flowchart: { curve: "basis", nodeSpacing: 40, rankSpacing: 56, padding: 14, htmlLabels: false },
  };
}

// Memoised; a failed or timed-out import resets the memo so 'Try again' really retries.
let mermaidP = null;
function getMermaid() {
  mermaidP ||= withTimeout(window.mermaid ? Promise.resolve() : loadScript(MERMAID), 10000).then(() => {
    window.mermaid.initialize(mermaidConfig());
    return window.mermaid;
  }).catch((e) => { mermaidP = null; throw e; });
  return mermaidP;
}
// Warm mermaid once the page has painted, but only on a stage that has a diagram.
let mermaidWarmed = false;
function warmMermaid() {
  if (mermaidWarmed) return;
  mermaidWarmed = true;
  idle(() => getMermaid().catch(() => {}));
}

// The diagram's type: the first word of its first line that is not front matter or a comment.
function diagramType(text) {
  const lines = text.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("%%"));
  if (lines[0] === "---") { const end = lines.indexOf("---", 1); lines.splice(0, end > 0 ? end + 1 : 1); }
  return ((lines[0] || "").match(/^[A-Za-z0-9-]+/) || [""])[0];
}

// Mermaid reads '<' and '>' in a flowchart label as markup. Inside label delimiters only — [..],
// (..), {..}, "..", |..| — they become mermaid's own entity codes; arrows outside stay as written,
// and so does a <br> line break. Every other diagram type is left alone: their arrows (--|>, ->>)
// hold the same characters.
const NOT_FLOW = /^(sequenceDiagram|classDiagram(-v2)?|stateDiagram(-v2)?|erDiagram|gantt|pie|mindmap|timeline|journey|gitGraph|quadrantChart|xychart(-beta)?|block(-beta)?|sankey(-beta)?|requirementDiagram|C4\w*|packet(-beta)?|architecture(-beta)?|kanban|radar(-beta)?)$/;
function escapeLabels(text) {
  if (NOT_FLOW.test(diagramType(text))) return text;
  const close = { "[": "]", "(": ")", "{": "}", '"': '"', "|": "|" };
  let out = "", open = null, shut = null, depth = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (!open) {
      if (c in close && !(c === "|" && text[i + 1] === ">")) { open = c; shut = close[c]; depth = 1; }
      out += c;
      continue;
    }
    if (c === "\n") { open = null; out += c; continue; }  // a label never spans lines
    if (c === shut && (open === shut || --depth === 0)) { open = null; out += c; continue; }
    if (c === open && open !== shut) depth++;
    const br = c === "<" && /^<br\s*\/?>/i.exec(text.slice(i, i + 8));
    if (br) { out += br[0]; i += br[0].length - 1; continue; }
    out += c === "<" ? "#lt;" : c === ">" ? "#gt;" : c;
  }
  return out;
}

// ---- Shell ---------------------------------------------------------------------------------

const ICON_PATHS = {
  code: '<path d="M5.5 4 2 8l3.5 4M10.5 4 14 8l-3.5 4"/>',
  diagram: '<rect x="1.5" y="1.5" width="6" height="4.5" rx="1.2"/><rect x="8.5" y="10" width="6" height="4.5" rx="1.2"/><path d="M4.5 6v3a1.5 1.5 0 0 0 1.5 1.5h2.5"/>',
  table: '<rect x="1.5" y="2.5" width="13" height="11" rx="1.6"/><path d="M1.5 6.5h13M6 6.5v7"/>',
  page: '<path d="M3.5 1.5h6l3 3v10h-9z"/><path d="M9.5 1.5v3h3M5.5 8.5h5M5.5 11h5"/>',
  change: '<path d="M4.5 2v6M1.5 5h6M8.5 12.5h6"/>',
  points: '<path d="M6 4h8M6 8h8M6 12h8"/><circle cx="2.6" cy="4" r=".9"/><circle cx="2.6" cy="8" r=".9"/><circle cx="2.6" cy="12" r=".9"/>',
};
const icon = (kind) => `<svg class="ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[kind] || ICON_PATHS.page}</svg>`;
const kindOf = (src) => (src.type !== "inline" ? "page" : src.format === "visual" ? "diagram"
  : src.format in ICON_PATHS ? src.format : "page");

const EMPTY_LINE = "When Claude shows code, a diagram, a table or a page, it appears here.";
const WC = window.WebCompanion;
const root = document.querySelector("[data-wc-root]") || document.body;
const embedded = window.parent !== window;
root.innerHTML = `<div class="stage">
  <div class="tabbar"><div class="tabnav" role="group" aria-label="Boards" hidden>
      <button type="button" class="nb navbtn prev" aria-label="Previous board"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg></button>
      <button type="button" class="nb navbtn next" aria-label="Next board"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg></button>
      <button type="button" class="pos" aria-haspopup="true" aria-expanded="false" aria-label="All boards"><span class="tabpos"></span><span class="posdot" hidden></span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
    </div>
    <div class="boards" hidden><h4>Boards, newest first</h4><nav class="tabs" role="tablist" aria-label="Stage" aria-orientation="vertical"></nav></div></div>
  <div class="panes"><div class="empty"><div class="emptycard">
    <h2>The stage is empty</h2><p class="msg">${EMPTY_LINE}</p>
    <div class="tiles">${["code", "diagram", "table", "page"].map((k) =>
      `<span class="tile">${icon(k)}<span>${k[0].toUpperCase() + k.slice(1)}</span></span>`).join("")}</div>
  </div></div></div>
</div>`;
const tabsEl = root.querySelector(".tabs"), panesEl = root.querySelector(".panes");
const navEl = root.querySelector(".tabnav"), boardsEl = root.querySelector(".boards"), posEl = root.querySelector(".pos");
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const views = new Map();            // name -> {body, tab, pane, filled, stale, renderSeq, changedAt, snap}
let layout = { order: [], front: null };
let live = false;                   // the first snapshot is in: from here a change is news
let follow = true;                  // embedded: boards come to the front as the voice reaches them
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const isDiagram = (body) => body.source.type === "inline" && body.source.format === "diagram";
const narrow = () => matchMedia("(max-width: 600px)").matches;
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, val) { try { localStorage.setItem(k, val); } catch {} },
};
libsReady();

function frameUrl(src, rev, hash) {
  if (src.type === "file") {
    const file = src.file.split("/").map(encodeURIComponent).join("/");
    return `${WC.api.BASE}mounts/${encodeURIComponent(src.mount)}/${file}?rev=${rev}` +
      (hash || (src.fragment ? "#" + src.fragment : ""));
  }
  if (src.type === "session") return `/s/${encodeURIComponent(src.sid)}/`;
  return src.url;
}

const span = (a, b) => (a === b ? `line ${a}` : `lines ${a}–${b}`);
// The first table's body rows, counted as talk counts them: after the separator, up to a blank line.
function tableRows(body) {
  const lines = body.split("\n").map((l) => l.trim());
  const sep = lines.findIndex((l) => /^\|?[\s:|-]+\|?$/.test(l) && l.includes("-"));
  if (sep < 0) return Math.max(lines.filter((l) => l.startsWith("|")).length - 1, 0);
  const end = lines.indexOf("", sep + 1);
  return (end < 0 ? lines.length : end) - sep - 1;
}

// The meta line in plain words, never a raw format name.
function metaText(src) {
  if (src.type === "file") return `${{ markdown: "Document", text: "File" }[src.display] || "Page"} · ${src.path}`;
  if (src.type === "url") { try { return `Page · ${new URL(src.url).host}`; } catch { return `Page · ${src.url}`; } }
  if (src.type === "session") return `${src.kind} · ${src.slug}`;
  if (src.format === "code") {
    const end = src.start + src.lines.length - 1;
    let t = `Code · ${src.path} · ${span(src.start, end)}`;
    if (src.highlight) t += ` · ${span(src.highlight[0], src.highlight[1])} marked`;
    if (src.truncated) t += " · showing the first 60 lines";
    return t;
  }
  if (src.format === "table") { const n = tableRows(src.body); return `Table · ${n} ${n === 1 ? "row" : "rows"}`; }
  if (src.format === "change") return `Change · ${src.path} · +${src.added} −${src.removed}` + (src.rev ? ` · since ${src.rev}` : "");
  if (src.format === "points") { const n = src.items.length; return `${n} key ${n === 1 ? "point" : "points"} from this call`; }
  if (src.format === "diagram") return "Diagram";
  if (src.format === "visual") return src.tool === "sequence" ? "Sequence diagram" : "Flowchart";
  return "Board";
}

function ago(t) {
  const s = (Date.now() - t) / 1000;
  if (s < 60) return "Updated just now";
  if (s < 3600) return `Updated ${Math.floor(s / 60)} min ago`;
  const h = Math.floor(s / 3600);
  return h < 24 ? `Updated ${h} ${h === 1 ? "hour" : "hours"} ago` : `Updated ${Math.floor(h / 24)} d ago`;
}
setInterval(() => { for (const v of views.values()) { const a = v.pane.querySelector(".vage"); if (a) a.textContent = ago(v.changedAt); } }, 30000);

function button(label, onclick, cls = "") {
  const b = document.createElement("button");
  b.type = "button"; b.className = "btn sm " + cls; b.textContent = label; b.onclick = onclick;
  return b;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return; } catch {}
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.cssText = "position:fixed;opacity:0"; document.body.append(ta);
  ta.select();
  try { if (!document.execCommand("copy")) throw new Error("copy failed"); } finally { ta.remove(); }
}

function header(v) {
  const { source: src, title, caption } = v.body;
  const h = document.createElement("header"); h.className = "phead";
  // One row: the title, with what the board is and when it changed in a tooltip, then its steps and buttons.
  h.innerHTML = `<div class="prow"><div class="vhead" tabindex="0">${icon(kindOf(src))}<h2 class="vtitle"></h2>
    <div class="vtip" role="tooltip"><p class="vmeta"><span></span></p><span class="vage"></span></div></div><div class="pbtns"></div></div>`;
  h.querySelector(".vtitle").textContent = title;
  const meta = h.querySelector(".vmeta span");
  if (src.type === "inline" && src.format === "change") {
    meta.innerHTML = `Change · ${esc(src.path)} · <b class="plus">+${+src.added}</b> <b class="minus">−${+src.removed}</b>` +
      (src.rev ? ` · since ${esc(src.rev)}` : "");
  } else meta.textContent = metaText(src);
  if (v.body.answer && !(src.type === "inline" && src.format === "points")) meta.append(` · from answer ${+v.body.answer}`);
  if (hasScene(v)) {
    const repairs = +(painted(v)?.scene.repairs) || 0;
    if (repairs) meta.append(` · ${repairs} ${repairs === 1 ? "repair" : "repairs"}`);
    const bar = document.createElement("span"); bar.className = "stepbar";
    const back = button("", () => stepBy(v, -1), "stepback"), next = button("", () => stepBy(v, 1), "stepnext");
    back.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>`; next.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>`;
    const step = document.createElement("span"); step.className = "vstep";
    back.setAttribute("aria-label", "Previous step"); next.setAttribute("aria-label", "Next step");
    bar.append(back, step, next);
    h.querySelector(".prow").insertBefore(bar, h.querySelector(".pbtns"));
  }
  h.querySelector(".vage").textContent = ago(v.changedAt);
  if (caption) {
    const c = document.createElement("p"); c.className = "vcaption"; c.textContent = caption; h.append(c);
  }
  const btns = h.querySelector(".pbtns");
  if (src.type !== "inline") {
    const a = document.createElement("a");
    a.className = "btn sm open"; a.target = "_blank"; a.rel = "noopener"; a.textContent = "Open ↗";
    a.href = frameUrl(src, v.body.rev);
    btns.append(a);
  } else if (["code", "table", "diagram", "change", "points", "visual"].includes(src.format)) {
    const text = () => src.format === "code" ? src.lines.join("\n") : src.format === "change" ? unifiedText(src)
      : src.format === "points" ? src.items.map((it) => `${it.n}. ${it.text}`).join("\n")
      : src.format === "visual" ? JSON.stringify(src.spec, null, 2) : src.body;
    const copy = button("Copy", async () => {
      copy.textContent = await copyText(text()).then(() => "Copied", () => "Copy failed");
      clearTimeout(copy._t); copy._t = setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    btns.append(copy);
  }
  if (src.type === "inline" && (src.format === "code" || src.format === "change")) {
    const wrap = button("Wrap lines", () => {
      const on = wrap.getAttribute("aria-pressed") !== "true";
      store.set("stage.wrap", on ? "1" : "0");
      for (const b of panesEl.querySelectorAll(".btn.wrapbtn")) b.setAttribute("aria-pressed", String(on));
      for (const c of panesEl.querySelectorAll(".code.lines-box")) c.classList.toggle("wrap", on);
    }, "wrapbtn");
    wrap.setAttribute("aria-pressed", String(wrapOn()));
    btns.append(wrap);
  }
  if (src.type === "inline" && src.format === "diagram") {
    const seg = document.createElement("div"); seg.className = "seg"; seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Diagram size");
    const set = (actual) => {
      v.actual = actual;
      fit.setAttribute("aria-pressed", String(!actual)); real.setAttribute("aria-pressed", String(actual));
      const box = v.pane.querySelector(".diagram, .visual");
      if (box) { box.classList.toggle("fit", !actual); box.classList.toggle("actual", actual); }
    };
    const fit = button("Fit", () => set(false)), real = button("Actual size", () => set(true));
    seg.append(fit, real); btns.append(seg);
    set(!!v.actual);
  }
  return h;
}

function wrapOn() {
  const saved = store.get("stage.wrap");
  return saved === null ? narrow() : saved === "1";
}

// A one-line note above a fallback, with a visible button when trying again can help.
function note(box, text, retry) {
  const p = document.createElement("p"); p.className = "note";
  p.append(text);
  if (retry) p.append(button("Try again", retry));
  box.before(p);
}

// ---- Code ----------------------------------------------------------------------------------

// Splits highlighted HTML into lines: at each newline the open spans close and reopen on the
// next line, so a string or docstring that spans lines keeps its colour on every one.
function splitLines(html) {
  const out = [], stack = [];
  let cur = "";
  for (const [tok] of html.matchAll(/<span[^>]*>|<\/span>|\n|[^<\n]+|</g)) {
    if (tok === "\n") { out.push(cur + "</span>".repeat(stack.length)); cur = stack.join(""); continue; }
    if (tok === "</span>") stack.pop(); else if (tok.startsWith("<span")) stack.push(tok);
    cur += tok;
  }
  out.push(cur + "</span>".repeat(stack.length));
  return out;
}

function highlightLines(lines, lang) {
  if (window.hljs) {
    const language = window.hljs.getLanguage(lang) ? lang : "plaintext";
    try { return splitLines(window.hljs.highlight(lines.join("\n"), { language, ignoreIllegals: true }).value); } catch {}
  }
  return lines.map(esc);
}

function paintCode(v, box, src) {
  const [ha, hb] = src.highlight || [0, -1];
  const html = highlightLines(src.lines, src.lang);
  const inner = document.createElement("div"); inner.className = "lines";
  inner.replaceChildren(...src.lines.map((_, i) => {
    const n = src.start + i, row = document.createElement("div");
    row.className = "ln" + (n >= ha && n <= hb ? " marked" : "");
    row.dataset.line = n;
    row.style.setProperty("--ind", indentOf(src.lines[i]));
    row.innerHTML = `<i>${n}</i><span>${html[i] ?? ""}</span>`;
    return row;
  }));
  box.classList.toggle("marks", !!src.highlight && src.lines.some((_, i) => src.start + i >= ha && src.start + i <= hb));
  box.replaceChildren(inner);
  pulseDiff(v, box, "code", src.lines);
  paintSpot(v, box);
  paintFrame(v, box);
}

// A line's leading whitespace in columns (a tab is 4), so a wrapped line continues under its first word.
function indentOf(line) {
  let n = 0;
  for (const c of String(line)) { if (c === " ") n++; else if (c === "\t") n += 4 - (n % 4); else break; }
  return Math.min(n, 40);
}

// On first show, the first marked line sits about a third of the way down.
function scrollToMark(box) {
  if (box.querySelector(".ln.spot")) return;  // a spot being spoken about wins
  const first = box.querySelector(".ln.marked");
  if (first) box.scrollTop = Math.max(0, first.offsetTop - box.clientHeight / 3);
}

// ---- Changes -------------------------------------------------------------------------------

function unifiedText(src) {
  const out = [`--- a/${src.path}`, `+++ b/${src.path}`];
  for (const h of src.hunks) { out.push(h.header); for (const r of h.lines) out.push(r.op + r.text); }
  return out.join("\n");
}

// Wraps characters a..b of a highlighted line's text in <mark class="chg">, piece by piece, so the
// highlighting spans around them stay whole. Entities count as one character.
function markRange(html, a, b) {
  if (a >= b) return html;
  let pos = 0, out = "";
  for (const [tok] of html.matchAll(/<[^>]*>|&[#\w]+;|[^<&]+|[<&]/g)) {
    if (tok[0] === "<" && tok.length > 1) { out += tok; continue; }
    const chars = tok[0] === "&" && tok.length > 1 ? [tok] : [...tok];
    let run = "", on = false, first = false, last = false;
    const flush = () => {
      if (run) out += on ? `<mark class="chg${first ? " s" : ""}${last ? " e" : ""}">${run}</mark>` : run;
      run = ""; first = last = false;
    };
    for (const c of chars) {
      const inside = pos >= a && pos < b;
      if (inside !== on) { flush(); on = inside; }
      if (inside && pos === a) first = true;
      if (inside && pos === b - 1) last = true;
      run += c; pos++;
    }
    flush();
  }
  return out;
}

// For a run of removed lines followed by as many added lines, each pair's differing middle.
function pairEdits(rows) {
  const spans = new Map();  // row index -> [a, b] in its text
  for (let i = 0; i < rows.length;) {
    if (rows[i].op !== "-") { i++; continue; }
    let j = i; while (j < rows.length && rows[j].op === "-") j++;
    let k = j; while (k < rows.length && rows[k].op === "+") k++;
    if (k - j === j - i) {
      for (let p = 0; p < j - i; p++) {
        const o = [...rows[i + p].text], n = [...rows[j + p].text];
        let pre = 0; while (pre < o.length && pre < n.length && o[pre] === n[pre]) pre++;
        let suf = 0; while (suf < o.length - pre && suf < n.length - pre && o[o.length - 1 - suf] === n[n.length - 1 - suf]) suf++;
        if (pre + suf === 0) continue;  // nothing in common: the whole line changed, so no mark
        // Whole words: "30" -> "90" marks both numbers, not one digit.
        const word = (c) => /[\p{L}\p{N}_]/u.test(c || "");
        while (pre > 0 && word(o[pre - 1])) pre--;
        while (suf > 0 && word(o[o.length - suf]) && word(n[n.length - suf])) suf--;
        spans.set(i + p, [pre, o.length - suf]); spans.set(j + p, [pre, n.length - suf]);
      }
    }
    i = k;
  }
  return spans;
}

function paintChange(v, box, src) {
  const inner = document.createElement("div"); inner.className = "lines";
  const rows = [], texts = [];
  for (const h of src.hunks) {
    const sep = document.createElement("div"); sep.className = "hunk";
    sep.innerHTML = `<span>Line ${+h.start_new}</span>`;
    rows.push(sep);
    // Each side is highlighted whole, so a string that spans lines keeps its colour.
    const oldIdx = [], newIdx = [];
    h.lines.forEach((r, i) => { if (r.op !== "+") oldIdx.push(i); if (r.op !== "-") newIdx.push(i); });
    const html = new Array(h.lines.length);
    const oldHtml = highlightLines(oldIdx.map((i) => h.lines[i].text), src.lang);
    oldIdx.forEach((i, k) => { html[i] = oldHtml[k]; });
    const newHtml = highlightLines(newIdx.map((i) => h.lines[i].text), src.lang);
    newIdx.forEach((i, k) => { html[i] = newHtml[k]; });
    const spans = pairEdits(h.lines);
    h.lines.forEach((r, i) => {
      const row = document.createElement("div");
      row.className = "ln " + (r.op === "+" ? "add" : r.op === "-" ? "del" : "ctx");
      if (r.new != null) row.dataset.line = r.new;
      row.style.setProperty("--ind", indentOf(r.text));
      const span = spans.get(i);
      const code = span ? markRange(html[i] ?? "", span[0], span[1]) : (html[i] ?? "");
      row.innerHTML = `<i>${r.old ?? ""}</i><i>${r.new ?? ""}</i><b aria-hidden="true">${r.op === "+" ? "+" : r.op === "-" ? "−" : ""}</b><span>${code}</span>`;
      row.setAttribute("aria-label", (r.op === "+" ? "added" : r.op === "-" ? "removed" : "unchanged") + " line");
      rows.push(row); texts.push(r.op + r.text);
    });
  }
  inner.replaceChildren(...rows);
  box.replaceChildren(inner);
  pulseDiff(v, box, "code", texts);
  paintSpot(v, box);
  paintFrame(v, box);
}

// ---- Key points ----------------------------------------------------------------------------

// The key point the voice reached last: it keeps the bar, and glows once when it is said.
let keyLit = 0;

function paintPoints(v, box, src) {
  const groups = new Map();
  for (const it of src.items) {
    if (!groups.has(it.answer)) groups.set(it.answer, []);
    groups.get(it.answer).push(it);
  }
  const prev = new Set(v.prev?.points || []);
  const fresh = v.prev ? src.items.filter((it) => !prev.has(it.n + "|" + it.text)) : [];
  v.prev = null;
  v.snap = { points: src.items.map((it) => it.n + "|" + it.text) };
  box.replaceChildren(...[...groups.entries()].sort((a, b) => a[0] - b[0]).map(([answer, items]) => {
    const sec = document.createElement("section"); sec.className = "kgroup";
    const cap = document.createElement("p"); cap.className = "kcap"; cap.textContent = answer ? `Answer ${answer}` : "Earlier";
    const ol = document.createElement("ol"); ol.className = "klist";
    for (const it of items.sort((a, b) => a.n - b.n)) {
      const li = document.createElement("li"); li.dataset.n = it.n;
      li.className = it.n === keyLit ? "lit" : "";
      li.innerHTML = `<span class="kn" aria-hidden="true">${+it.n}</span><span class="kt"></span>`;
      li.querySelector(".kt").textContent = it.text;
      ol.append(li);
    }
    sec.append(cap, ol);
    return sec;
  }));
  for (const it of fresh) restart(box.querySelector(`li[data-n="${+it.n}"]`), "changed");
  // The newest answer's points are the ones to read: bring them into view, unless one is lit.
  requestAnimationFrame(() => {
    const lit = box.querySelector("li.lit"), body = box.closest(".pbody"), last = box.lastElementChild;
    if (!body || body.closest(".pane")?.hidden) return;
    if (lit) centre(lit);
    else if (last) body.scrollTop += last.getBoundingClientRect().top - body.getBoundingClientRect().top - 16;
  });
}

function lightKey(n, glow = true) {
  keyLit = n;
  for (const v of views.values()) {
    if (v.body.source.format !== "points") continue;
    const box = v.pane.querySelector(".points");
    if (!box) continue;
    for (const li of box.querySelectorAll("li.lit")) li.classList.remove("lit");
    const li = box.querySelector(`li[data-n="${+n}"]`);
    if (!li) continue;
    li.classList.add("lit"); if (glow) restart(li, "glow");
    if (!v.pane.hidden) requestAnimationFrame(() => { if (li.isConnected) centre(li); });
  }
}

// ---- Tables --------------------------------------------------------------------------------

const NUM = /^[-+]?[\d.,]+ ?(%|ms|s|KB|MB|GB|€|\$)?$/;

// Markdown as the stage shows it: sanitized; a relative link or image read against the file it came
// from; a link out opening in a new tab, so the stage is never navigated away; headings given ids
// (prefixed, never clashing with the page's own) that the document's #links scroll to.
const slug = (t) => "md-" + String(t).trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-");
function markdownInto(box, text, base = null) {
  box.innerHTML = DOMPurify.sanitize(marked.parse(text), { FORBID_TAGS: ["form", "meta", "iframe", "style", "base"] });
  for (const el of box.querySelectorAll("[src], a[href]")) {
    const attr = el.hasAttribute("src") ? "src" : "href", raw = el.getAttribute(attr);
    if (raw.startsWith("#")) { el.setAttribute("href", "#" + slug(decodeURIComponent(raw.slice(1)))); continue; }
    if (base) { try { el.setAttribute(attr, new URL(raw, base).href); } catch {} }
    if (el.tagName === "A") { el.target = "_blank"; el.rel = "noopener"; }
  }
  for (const h of box.querySelectorAll("h1, h2, h3, h4, h5, h6")) if (!h.id) h.id = slug(h.textContent);
  box.onclick = (e) => {
    const a = e.target.closest?.('a[href^="#"]');
    if (!a) return;
    e.preventDefault();
    box.querySelector(`[id="${CSS.escape(a.getAttribute("href").slice(1))}"]`)?.scrollIntoView({ block: "start" });
  };
}

// After marked: each table in its own scrolling box, with uniform column rules.
function shapeTables(box) {
  for (const table of box.querySelectorAll("table")) {
    const wrap = document.createElement("div"); wrap.className = "tablewrap";
    table.before(wrap); wrap.append(table);
    const heads = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
    const rows = [...table.querySelectorAll("tbody tr")].map((tr) => [...tr.children]);
    const cols = Math.max(heads.length, ...rows.map((r) => r.length), 0);
    for (const r of rows) r.forEach((td, i) => { if (heads[i]) td.dataset.label = heads[i]; });
    const colCells = (i) => rows.map((r) => r[i]).filter(Boolean);
    const all = (i, test) => colCells(i).length > 0 && colCells(i).every((td) => test(td.textContent.trim()));
    if (all(0, (t) => t.length <= 28)) {
      for (const tr of table.querySelectorAll("tr")) tr.children[0]?.classList.add("key");
    }
    for (let i = 0; i < cols; i++) {
      if (!all(i, (t) => NUM.test(t))) continue;
      for (const tr of table.querySelectorAll("tr")) tr.children[i]?.classList.add("num");
    }
    if (cols >= 3) { table.classList.add("cards"); wrap.classList.add("cards"); }
  }
}

function paintTable(v, box, src) {
  if (!hasMarkdown()) { box.innerHTML = `<pre>${esc(src.body)}</pre>`; return; }
  markdownInto(box, src.body);
  shapeTables(box);
  box.classList.add("grid");  // a table board: the wide grid, its row being said the large one
  pulseDiff(v, box, "rows", [...box.querySelectorAll("tbody tr")].map((tr) => tr.textContent));
  paintSpot(v, box);
  paintFrame(v, box);
}

// ---- Motion --------------------------------------------------------------------------------

// An in-place update of the view being read: what changed glows and fades. `v.prev` is the
// view's last painted rows or lines, set by fillPane only for such an update.
function pulseDiff(v, box, what, now) {
  const prev = v.prev?.[what];
  v.snap = { [what]: now };
  if (!prev) return;
  v.prev = null;
  const els = box.querySelectorAll(what === "code" ? ".ln" : "tbody tr");
  now.forEach((t, i) => { if (prev[i] !== t) restart(els[i], "changed"); });
}
function restart(el, cls) {
  if (!el) return;
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
  el.addEventListener("animationend", () => el.classList.remove(cls), { once: true });
}

// ---- Diagrams ------------------------------------------------------------------------------

// Fit: up to twice as drawn, never wider or taller than the pane. Actual size: as drawn.
function sizeSvg(box) {
  const svg = box.querySelector("svg"); if (!svg) return;
  const vb = svg.viewBox?.baseVal;
  if (vb && vb.width) { svg.style.setProperty("--w", vb.width + "px"); svg.style.setProperty("--h", vb.height + "px"); }
  svg.removeAttribute("height");
}

// Returns the box at once. Anything that waits (libraries, mermaid) fills it later, and only
// while the view still shows the body it started from: `seq` is the fill it belongs to.
function renderInline(v, seq) {
  const src = v.body.source, box = document.createElement("div");
  const current = () => v.renderSeq === seq && box.isConnected;
  const retryLibs = () => { libsP = null; fillPane(v); };
  if (src.format === "code") {
    box.className = "code lines-box" + (wrapOn() ? " wrap" : "");
    paintCode(v, box, src);
    if (!window.hljs) libsReady().then(() => {
      if (!current()) return;
      if (window.hljs) paintCode(v, box, src); else note(box, "Highlighting did not load, so this is plain text.", retryLibs);
    });
  } else if (src.format === "change") {
    box.className = "code lines-box change" + (wrapOn() ? " wrap" : "");
    paintChange(v, box, src);
    if (!window.hljs) libsReady().then(() => {
      if (!current()) return;
      if (window.hljs) paintChange(v, box, src); else note(box, "Highlighting did not load, so this is plain text.", retryLibs);
    });
  } else if (src.format === "points") {
    box.className = "points";
    paintPoints(v, box, src);
  } else if (src.format === "visual" && src.tool === "sequence") {
    // A sequence unfolds with the voice as lanes: every arrow carries its sentence, no numbered key.
    box.className = "visual lanes";
    renderLanes(box, src.spec, embedded);
    requestAnimationFrame(() => { if (current()) paintFrame(v, box); });
  } else if (src.format === "visual" && src.tool === "flowchart") {
    // A flowchart is a map the stage draws itself: ghosts first, lit part by part with the voice.
    box.className = "visual map";
    renderMap(box, src.spec, embedded);
    requestAnimationFrame(() => { if (current()) { paintFrame(v, box); if (!hasScene(v)) layoutMap(box, null); } });
  } else if (src.format === "visual") {
    box.className = `visual visual-${src.tool} ` + (v.actual ? "actual" : "fit");
    box.innerHTML = `<div class="vinner"><div class="vgrid">${src.html}</div>` +
      (src.key ? `<div class="vkey">${src.key}</div>` : "") + "</div>";
    ownMarkers(box);
    sizeSvg(box);
    paintSpot(v, box);
    requestAnimationFrame(() => { if (current()) paintFrame(v, box); });
  } else if (src.format === "diagram") {
    box.className = "diagram drawing";
    box.innerHTML = `<div class="spin"></div><span>Drawing the diagram…</span>`;
    drawDiagram(v, seq, box, current);
  } else {
    box.className = "md";
    paintTable(v, box, src);
    if (!hasMarkdown()) libsReady().then(() => {
      if (!current()) return;
      if (hasMarkdown()) paintTable(v, box, src); else note(box, "The table formatter did not load, so this is the plain text.", retryLibs);
    });
  }
  return box;
}

function sourceFrame(text) {
  const pre = document.createElement("pre"); pre.className = "srcframe"; pre.textContent = text;
  return pre;
}

// Detached from the delta queue: the queue never awaits mermaid.
// A stage the page around it has hidden (talk's Conversation view on a tablet) has no size, and
// mermaid lays a diagram out at the size it is drawn at: such a diagram waits, marked stale, and is
// drawn once the stage has a size again (the ResizeObserver below), or when its tab is opened.
const unsized = (box) => !box.isConnected || !document.documentElement.clientWidth || !box.clientWidth;

async function drawDiagram(v, seq, box, current) {
  const id = "m" + Math.random().toString(36).slice(2);
  const body = v.body.source.body, pulse = v.prev?.diagram;
  v.prev = null;
  let mermaid;
  try { mermaid = await getMermaid(); } catch (e) {
    if (!current()) return;
    box.className = "diagram failed"; box.replaceChildren(sourceFrame(body));
    note(box, `The diagram library did not load (${e.message}), so this is the diagram's source.`, () => fillPane(v));
    return;
  }
  if (!current()) return;
  if (unsized(box)) { v.stale = true; return; }
  try {
    const { svg } = await mermaid.render(id, escapeLabels(body));
    if (!current()) return;
    if (unsized(box)) { v.stale = true; return; }
    box.className = "diagram " + (v.actual ? "actual" : "fit"); box.innerHTML = svg;
    sizeSvg(box);
    // A layout of next to nothing means it was drawn with no room: draw it again when there is.
    const vb = box.querySelector("svg")?.viewBox?.baseVal;
    if (vb && vb.width <= 16) v.stale = true;
    if (pulse) restart(box, "pulse");
    paintSpot(v, box);
    paintFrame(v, box);
  } catch (e) {
    document.getElementById("d" + id)?.remove();
    if (!current()) return;
    box.className = "diagram failed";
    const card = document.createElement("div"); card.className = "failcard";
    card.innerHTML = `<p class="fail-h">This diagram could not be drawn.</p><p class="fail-e"></p>`;
    card.querySelector(".fail-e").textContent = String(e?.message || e).split("\n")[0];
    card.append(button("Try again", () => fillPane(v)));
    box.replaceChildren(card, sourceFrame(body));
  }
}

// Theme switch (the system's, or the call page's): every diagram is stale; only the visible one
// redraws now. Mermaid takes its colours when it draws, so each needs drawing again.
async function redrawDiagrams() {
  if (mermaidP) { try { (await mermaidP).initialize(mermaidConfig()); } catch {} }
  for (const v of views.values()) {
    if (!isDiagram(v.body) || !v.filled) continue;
    if (v.pane.hidden) v.stale = true; else fillPane(v);
  }
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawDiagrams);

// A page board takes the theme the call page set. A page from this daemon's origin gets data-theme
// on its <html>, which a page written with the shared rules (:root[data-theme="dark"] beside the
// prefers-color-scheme query) follows as it is. A page from another origin cannot be reached, so it
// gets the theme as a message and follows only if it listens. A stage opened on its own sets no theme.
function themeFrame(frame) {
  const theme = document.documentElement.dataset.theme;
  if (!theme) return;
  try { frame.contentDocument.documentElement.dataset.theme = theme; } catch {}
  try { frame.contentWindow.postMessage({ type: "stage:theme", theme }, "*"); } catch {}
}

// The stage got a size back: draw what waited for one, in the pane on show.
new ResizeObserver(() => {
  if (!document.documentElement.clientWidth) return;
  for (const v of views.values()) if (v.stale && v.filled && !v.pane.hidden) fillPane(v);
}).observe(document.documentElement);

// ---- Panes ---------------------------------------------------------------------------------

// `update`: an in-place change to the view being read, so what changed may pulse.
function fillPane(v, update = false) {
  const { source: src, rev, title } = v.body;
  const seq = v.renderSeq = (v.renderSeq || 0) + 1;
  const first = !v.filled;
  v.prev = update ? { ...v.snap, diagram: true } : null;
  v.filled = true; v.stale = false; v.applied = null;
  const body = document.createElement("div"); body.className = "pbody";
  v.pane.replaceChildren(header(v), body);
  if (src.type === "inline") {
    const box = renderInline(v, seq);
    body.append(box);
    if (src.format === "code" && first) requestAnimationFrame(() => scrollToMark(box));
    if (src.format === "change" && src.more > 0) {
      const more = document.createElement("p"); more.className = "more";
      more.textContent = `${src.more} more changed ${src.more === 1 ? "line" : "lines"} not shown`;
      body.append(more);
    }
    return;
  }
  v.prev = null;
  if (src.type === "file" && src.missing) {
    const p = document.createElement("p"); p.className = "waiting";
    p.textContent = `Waiting for ${src.path}`; body.append(p); return;
  }
  if (src.type === "file" && src.display && src.display !== "page") { paintFile(v, body, seq); return; }
  const wrap = document.createElement("div"); wrap.className = "framewrap";
  const frame = document.createElement("iframe");
  frame.className = "frame"; frame.title = title; frame.src = frameUrl(src, rev);
  frame.addEventListener("load", () => themeFrame(frame));
  wrap.append(frame);
  body.append(wrap);
  if (update) restart(wrap, "pulse");
}

// A file a browser would download from a frame: read it, then show Markdown as a document and
// anything else as text. A save repaints it in place, where the reader had scrolled to.
function paintFile(v, body, seq) {
  const src = v.body.source, top = v.fileTop || 0;
  const box = document.createElement("div");
  box.className = src.display === "markdown" ? "md doc" : "code";
  box.addEventListener("scroll", () => { v.fileTop = box.scrollTop; });
  body.append(box);
  const current = () => v.renderSeq === seq && box.isConnected;
  const paint = (text) => {
    if (src.display === "markdown" && hasMarkdown()) {
      markdownInto(box, text, new URL(frameUrl(src, v.body.rev, "#"), location.href));
    } else {
      const pre = document.createElement("pre"); pre.className = "filetext"; pre.textContent = text;
      box.replaceChildren(pre);
    }
    const anchor = !top && src.fragment && box.querySelector(`[id="${CSS.escape(slug(src.fragment))}"]`);
    if (anchor) requestAnimationFrame(() => anchor.scrollIntoView({ block: "start" }));
    else box.scrollTop = top;
  };
  fetch(frameUrl(src, v.body.rev, "#"))
    .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${r.status}`))))
    .then((text) => {
      if (!current()) return;
      paint(text);
      if (src.display === "markdown" && !hasMarkdown()) libsReady().then(() => { if (current() && hasMarkdown()) paint(text); });
    })
    .catch((err) => { if (current()) note(box, `${src.path} could not be read (${err.message}).`, () => fillPane(v)); });
}

// Double-buffered: the new frame loads hidden over the old one and takes its place only once
// it has loaded and been scrolled to where the reader was, so a save never flashes blank.
function reloadFrame(v) {
  const wrap = v.pane.querySelector(".framewrap");
  const old = wrap?.querySelector("iframe.frame:not(.incoming)");
  if (!old) return fillPane(v);
  let hash = "", x = 0, y = 0;
  try { const w = old.contentWindow; hash = w.location.hash; x = w.scrollX; y = w.scrollY; } catch {}
  wrap.querySelector("iframe.incoming")?.remove();  // a newer save supersedes a reload still loading
  const next = document.createElement("iframe");
  next.className = "frame incoming"; next.title = old.title;
  let timer;
  const swap = () => {
    clearTimeout(timer);
    if (!next.isConnected) return;
    next.classList.remove("incoming");
    for (const f of wrap.querySelectorAll("iframe.frame")) if (f !== next) f.remove();
    if (!v.pane.hidden) restart(wrap, "pulse");
  };
  next.addEventListener("load", () => { themeFrame(next); try { next.contentWindow.scrollTo(x, y); } catch {} swap(); }, { once: true });
  timer = setTimeout(swap, 10000);  // never loaded: fall back to a plain swap
  next.src = frameUrl(v.body.source, v.body.rev, hash);
  wrap.append(next);
  const open = v.pane.querySelector(".open");
  if (open) open.href = frameUrl(v.body.source, v.body.rev);
  const age = v.pane.querySelector(".vage");
  if (age) age.textContent = ago(v.changedAt);
}

// ---- Tabs ----------------------------------------------------------------------------------

function setTabTitle(v) {
  v.tab.querySelector(".ttl").textContent = v.body.title;
  v.tab.title = v.body.title;
  v.tab.querySelector(".ico")?.remove();
  v.tab.insertAdjacentHTML("afterbegin", icon(kindOf(v.body.source)));
  v.tab.querySelector(".count")?.remove();
  const src = v.body.source;
  if (src.type === "inline" && src.format === "points") {
    const c = document.createElement("span"); c.className = "count";
    c.textContent = src.items.length; c.title = `${src.items.length} key points`;
    v.tab.append(c);
  }
  markUpdated(v, v.tab.classList.contains("updated"));
}
function markUpdated(v, on) {
  v.tab.classList.toggle("updated", on);
  if (on) v.tab.setAttribute("aria-label", v.body.title + ", updated"); else v.tab.removeAttribute("aria-label");
  updateNav();
}

// The boards are one stage with a history: ‹ and › walk it, "2 of 5" opens the list of every board, newest
// first, and its dot says a board changed while another was in front. The tabs are the list's rows.
function updateNav() {
  const tabs = [...tabsEl.children], i = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
  navEl.hidden = tabs.length < 2;
  if (navEl.hidden) showBoards(false);
  navEl.querySelector(".tabpos").textContent = i >= 0 ? `${i + 1} of ${tabs.length}` : `${tabs.length} boards`;
  navEl.querySelector(".prev").disabled = i <= 0;
  navEl.querySelector(".next").disabled = i < 0 || i >= tabs.length - 1;
  const changed = tabs.some((t) => t.classList.contains("updated") && t.getAttribute("aria-selected") !== "true");
  navEl.querySelector(".posdot").hidden = !changed;
  posEl.setAttribute("aria-label", "All boards" + (changed ? ", one changed" : ""));
}
// The pane headers start after the history buttons, which sit over their left end.
new ResizeObserver(() => root.querySelector(".stage").style.setProperty("--navw", navEl.offsetWidth + "px")).observe(navEl);
function step(d) {
  const tabs = [...tabsEl.children], i = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
  const next = tabs[i + d];
  if (next) next.click();
}
navEl.querySelector(".prev").onclick = () => step(-1);
navEl.querySelector(".next").onclick = () => step(1);
function showBoards(on) {
  boardsEl.hidden = !on; posEl.setAttribute("aria-expanded", String(on));
  // Scrolls the list itself only: scrollIntoView would also scroll the page around an embedded stage.
  const sel = on && tabsEl.querySelector('[aria-selected="true"]');
  if (sel) boardsEl.scrollTop = Math.max(0, sel.offsetTop - boardsEl.clientHeight / 2);
}
// In a call, Space and ← → steer the answer being read, as they do on the call page: the stage passes them on
// when nothing here takes keys (a button, a field, the list), instead of scrolling the board.
if (embedded) document.addEventListener("keydown", (e) => {
  if (![" ", "ArrowLeft", "ArrowRight"].includes(e.key) || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
  const at = document.activeElement;
  if (at && at !== document.body && at.closest("button, a, input, textarea, select, [contenteditable], [tabindex], .boards")) return;
  e.preventDefault();
  if (!(e.key === " " && e.repeat)) post({ type: "stage:key", key: e.key });
});
posEl.onclick = (e) => { e.stopPropagation(); showBoards(boardsEl.hidden); };
document.addEventListener("click", (e) => { if (!boardsEl.hidden && !e.target.closest(".boards")) showBoards(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !boardsEl.hidden) { showBoards(false); posEl.focus(); } });

// Panes fill lazily: only the one being shown is rendered, and a hidden pane whose body
// changed is refilled the next time it is shown. `arrive`: fronted by Claude, not a click.
function select(name, arrive = false) {
  const was = selectedName();
  for (const [n, v] of views) {
    const on = n === name;
    if (on && (!v.filled || v.stale)) fillPane(v);
    v.tab.setAttribute("aria-selected", String(on));
    v.pane.hidden = !on;
    if (on) {
      markUpdated(v, false);
      if (arrive && live && was !== n) { restart(v.pane, "arrive"); restart(v.tab, "flash"); }
    }
  }
  if (was !== name) post({ type: "stage:shown", view: name });  // the call's Play plays the board in front
}

// A pinned view (Key points) leads the history, whatever the layout's order, so the list shows it last.
function reorderTabs() {
  let names = layout.order.filter((n) => views.has(n));
  for (const n of views.keys()) if (!names.includes(n)) names.push(n);
  names = [...names.filter((n) => views.get(n).body.pinned), ...names.filter((n) => !views.get(n).body.pinned)];
  for (const n of names) { tabsEl.append(views.get(n).tab); }
  panesEl.querySelector(".empty")?.toggleAttribute("hidden", views.size > 0);
  updateNav();
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
  select(views.has(layout.front) ? layout.front : names[names.length - 1], true);
  postViews();
}

// A view upserting or disappearing only reorders tabs; it must never pull the viewer away
// from what they're reading unless nothing was selected, or the selected view is the one
// that just vanished.
function afterViewChange(removedName) {
  const names = reorderTabs();
  const sel = selectedName();
  if (!sel || sel === removedName) select(views.has(layout.front) ? layout.front : names[names.length - 1], true);
  postViews();
}

function upsert(body) {
  if (isDiagram(body)) warmMermaid();
  let v = views.get(body.name);
  if (!v) {
    const tab = document.createElement("button");
    tab.setAttribute("role", "tab"); tab.setAttribute("aria-selected", "false"); tab.dataset.view = body.name;
    tab.innerHTML = `<span class="ttl"></span>`;
    tab.onclick = () => { showBoards(false); if (selectedName() === body.name) return; select(body.name); toRest(views.get(body.name)); if (embedded && follow) setFollow(false); };
    const pane = document.createElement("section");
    pane.className = "pane"; pane.dataset.view = body.name; pane.hidden = true;
    panesEl.append(pane);
    v = { body, tab, pane, filled: false, stale: false, renderSeq: 0, changedAt: Date.now(), snap: null,
      frame: null, answer: null, applied: null };
    startFrame(v);
    views.set(body.name, v);
    setTabTitle(v);
    if (live) markUpdated(v, true);  // select() clears it if this view is the one fronted
    // The daemon lists __layout__ before the view it names, so a newly shown view arrives
    // after the layout that fronts it: bring it forward now. Only on creation — an update to
    // a view that already exists never moves the selection.
    if (body.name === layout.front) select(body.name, true);
    // A board the voice fronted before it got here comes forward now, as it would have then.
    else if (lateFront && lateFront.name === body.name) { const { answer } = lateFront; lateFront = null; front(body.name, false, answer); }
    if (live) post({ type: "stage:changed", name: body.name, title: body.title, isNew: true });
    return;
  }
  const before = v.body, was = sceneOf(v);
  v.body = body;
  const sceneChanged = !same(before.scene, body.scene) || !same(before.scenes, body.scenes);
  // A later answer's scene never takes the board from the answer whose voice is on it: only a change to the
  // scene the board is on starts it again.
  if (!same(was, sceneOf(v))) { startFrame(v); v.missReported = false; }
  const changed = !same(before.source, body.source) || before.title !== body.title ||
    before.rev !== body.rev || before.caption !== body.caption || sceneChanged;
  if (changed) v.changedAt = Date.now();
  if (live && (!same(before.source, body.source) || before.rev !== body.rev)) {
    post({ type: "stage:changed", name: body.name, title: body.title, isNew: false });
  }
  setTabTitle(v);
  if (changed && live && v.tab.getAttribute("aria-selected") !== "true") markUpdated(v, true);
  if (!v.filled) return;  // never shown: select() will render the latest body
  const { missing: m1, ...s1 } = before.source, { missing: m2, ...s2 } = body.source;
  if (same(s1, s2) && m1 === m2 && before.rev !== body.rev && body.source.type !== "inline") reloadFrame(v);
  else if (!same(before.source, body.source) || before.title !== body.title || before.caption !== body.caption || sceneChanged) {
    if (v.pane.hidden) v.stale = true; else fillPane(v, true);
  }
}

function remove(name) {
  const v = views.get(name); if (!v) return;
  v.renderSeq++;  // drop any diagram still drawing for it
  v.tab.remove(); v.pane.remove(); views.delete(name);
  updateNav();
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
  upsert(item.body);
  afterViewChange();
}

// ---- Following the voice (embedded in a talk call) ------------------------------------------

// The spot: what the voice is talking about, {name, target}. Kept here so a pane filled later
// (lazily, or after mermaid draws) lights it up too.
let spot = null;

// Following lives on the call page's gear; the stage keeps the state and tells the page when it
// changes here.
function setFollow(on) {
  if (follow === on) return;
  follow = on;
  post({ type: "stage:follow", on });
}

const fold = (t) => String(t).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();

// Centre `el` in each box around it that scrolls, inside the pane only: never the page around the stage.
function centre(el) {
  const behavior = reduced() ? "auto" : "smooth";
  for (let box = el.parentElement; box && box !== panesEl; box = box.parentElement) {
    if (box.scrollHeight <= box.clientHeight + 1 || !/auto|scroll/.test(getComputedStyle(box).overflowY)) continue;
    const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
    box.scrollTo({ top: box.scrollTop + (r.top + r.height / 2) - (b.top + b.height / 2), behavior });
  }
}

function clearSpots(scope = panesEl) {
  for (const el of scope.querySelectorAll(".spot")) el.classList.remove("spot");
  for (const el of scope.querySelectorAll(".dimmed")) el.classList.remove("dimmed");
}

// Lights up the spot in this view's painted box, if the spot is on this view. `box` is the box just
// painted (it may not be in the pane yet); without it, the pane's own.
function paintSpot(v, box) {
  box = box || v.pane.querySelector(".code, .md, .diagram, .visual");
  if (!box) return;
  clearSpots(box.parentElement || box);
  box.classList.remove("dimmed");
  if (!spot || spot.name !== v.body.name || !spot.target) return;
  const t = spot.target;
  let hits = [], holder = box;
  if (t.type === "lines") {
    hits = [...box.querySelectorAll(".ln")].filter((ln) => +ln.dataset.line >= t.a && +ln.dataset.line <= t.b);
  } else if (t.type === "row") {
    const rows = [...box.querySelectorAll("tbody tr")];
    const row = t.text != null ? rows.find((tr) => fold(tr.children[0]?.textContent || "") === fold(t.text)) : rows[t.n - 1];
    if (row) hits = [row];
    holder = row?.closest("table") || box;
  } else if (t.type === "node") {
    hits = nodeElements(box.querySelector("svg"), t.id).slice(0, 1);
  }
  if (!hits.length) return;
  for (const h of hits) h.classList.add("spot");
  holder.classList.add("dimmed");
  requestAnimationFrame(() => { if (hits[0].isConnected) centre(hits[0]); });
}

// The board the voice fronted before it reached the stage, {name, answer}: fronted when it arrives.
let lateFront = null;
function front(name, manual, answer = null) {
  if (!views.has(name) && manual) post({ type: "stage:missing", view: name });
  if (!follow && !manual) return false;
  lateFront = !views.has(name) && !manual ? { name, answer: answerKey(answer) } : null;
  if (!views.has(name)) return false;
  // A chip works as a tab tap: another board opens whole and the stage stops following the voice; the
  // board already in front keeps its frame and the following.
  if (manual) {
    if (selectedName() === name) return true;
    select(name, true); toRest(views.get(name));
    if (embedded) setFollow(false);
    return true;
  }
  // fronted by the voice of an answer that did not step this board: its picture is that answer's, from the start
  const v = views.get(name);
  if (hasScene(v) && onAnswer(v, answer)) {
    v.frame = sceneOf(v) ? 0 : null;
    if (v.filled && !v.stale) paintFrame(v);
  }
  if (selectedName() !== name) select(name, true);
  return true;
}

// Each answer that stepped a board keeps its own scene on it, in body.scenes under the answer's number, and
// body.scene is the scene of the answer that last put the board up (none when it showed the board whole).
// The board is on the scene of the answer whose voice drove it last (v.answer, from stage:frame, stage:state
// and stage:front), else on body.scene. A board saved before scenes were kept per answer has only
// body.scene, and is always on it.
function sceneOf(v) {
  const all = v.body.scenes;
  if (v.answer != null && all) return all[v.answer] || null;
  return v.body.scene || null;
}
const hasScene = (v) => !!(v.body.scene || Object.keys(v.body.scenes || {}).length);
// What the board paints: its scene at its frame, clamped to the rest frame. On an answer that showed the
// board without steps of its own, any of its scenes at rest: the whole board, which every rest frame is.
function painted(v) {
  const own = sceneOf(v);
  if (own) return { scene: own, n: Math.min(v.frame ?? own.rest, own.rest) };
  const any = v.body.scene || Object.values(v.body.scenes || {}).pop();
  return any ? { scene: any, n: any.rest } : null;
}
const answerKey = (a) => (a == null || a === "" ? null : String(a));
function onAnswer(v, answer) {
  const a = answerKey(answer);
  if (a === null || a === v.answer) return false;
  v.answer = a; v.applied = null;
  return true;
}

// A frame the voice sent for a board not here yet waits for it, with the answer it was for; another answer
// starting, or the next whole picture (stage:state), drops it.
const lateFrames = new Map();
// A board arriving, or one whose scene changed under it: a late frame for a scene it holds is applied now;
// else a scene shown during a call starts empty, for the voice to fill.
function startFrame(v) {
  const body = v.body, late = lateFrames.get(body.name);
  lateFrames.delete(body.name);
  v.applied = null;
  if (late && (late.answer === null || !body.scenes || body.scenes[late.answer])) {
    v.answer = late.answer; v.frame = late.n;
    return;
  }
  v.answer = null;
  v.frame = body.scene && embedded && live ? 0 : null;
}

// Every flowchart names its arrowhead fc-arrow, and url(#fc-arrow) finds the first in the page, which
// may sit in a hidden pane and draw nothing; each drawing gets markers of its own.
let markerSeq = 0;
function ownMarkers(box) {
  for (const m of box.querySelectorAll("marker[id]")) {
    const was = `url(#${m.id})`;
    m.id = `${m.id}-${++markerSeq}`;
    for (const el of box.querySelectorAll("[marker-end], [marker-start], [marker-mid]")) {
      for (const a of ["marker-end", "marker-start", "marker-mid"]) if (el.getAttribute(a) === was) el.setAttribute(a, `url(#${m.id})`);
    }
  }
}

function paintFrame(v, box, animate = false) {
  const on = painted(v);
  box = box || v.pane.querySelector(".code, .md, .diagram, .visual");
  if (!on || !box) return;
  const { scene, n } = on;
  const done = applyFrame(scene, box, n, animate && v.applied === n - 1 ? v.applied : null);
  if (!done) return;
  if (box.classList.contains("lanes")) { layoutLanes(box, scene, n); done.focused = null; }  // lanes scroll themselves
  if (box.classList.contains("map")) { layoutMap(box, scene, n); done.focused = null; }  // the map is placed to fit
  if (box.classList.contains("grid")) {
    const cur = new Set(beingSaid(scene, n).filter((k) => k.startsWith("row#")));
    for (const tr of box.querySelectorAll("tbody tr")) tr.classList.toggle("g-cur", cur.has(tr.dataset.key));
    box.classList.toggle("g-on", cur.size > 0);
    const row = box.querySelector("tbody tr.g-cur");
    if (row) done.focused = row;  // keep the row being said in view
  }
  v.applied = n;
  // Checked a frame later: a pane filled as it is fronted is still hidden while it paints.
  if (done.focused) requestAnimationFrame(() => { if (done.focused.isConnected && !v.pane.hidden) centre(done.focused); });
  const step = v.pane.querySelector(".vstep");
  if (step) step.textContent = stepLabel(scene, n);
  const back = v.pane.querySelector(".stepback"), next = v.pane.querySelector(".stepnext");
  if (back) back.disabled = n <= 0;
  if (next) next.disabled = n >= scene.rest;
  if (done.missing.length && !v.missReported) {
    v.missReported = true;
    post({ type: "stage:keymiss", view: v.body.name, keys: done.missing });
  }
}

// Back and Next move one frame, from the empty start to the rest frame. Stepping by hand takes the
// stage off the voice, as a tapped tab does, until the reader presses Play or the next answer starts.
function stepBy(v, delta) {
  if (!hasScene(v)) return;
  // on a board its answer showed whole, the steps are the newest scene's, from the rest frame
  if (!sceneOf(v)) { v.answer = Object.keys(v.body.scenes || {}).pop() ?? null; v.frame = null; v.applied = null; }
  const scene = sceneOf(v) || painted(v).scene;
  const n = Math.max(0, Math.min((v.frame ?? scene.rest) + delta, scene.rest));
  if (embedded && follow) setFollow(false);
  v.frame = n;
  if (v.filled && !v.stale) paintFrame(v, null, delta > 0);
}

// Frame n of the scene `answer` said the board with (no answer: the board's own scene), clamped to its rest.
function setFrame(name, n, animate, answer = null) {
  const v = views.get(name);
  if (!Number.isInteger(n) || n < 0) return;
  if (!v) { lateFrames.set(name, { n, answer: answerKey(answer) }); return; }
  if (!hasScene(v) || (!follow && selectedName() === name)) return;
  if (onAnswer(v, answer)) animate = false;
  const scene = sceneOf(v);
  v.frame = scene ? Math.min(n, scene.rest) : null;
  if (v.filled && !v.stale) paintFrame(v, null, animate);
}

function toRest(v) {
  if (!v || !hasScene(v) || v.frame === null) return;
  v.frame = null;
  if (v.filled && !v.stale) paintFrame(v);
}

function onMessage(m) {
  if (m.type === "stage:front") front(String(m.view), !!m.manual, m.answer);
  else if (m.type === "stage:key") {
    // Never fronted: the board in front stays on the explanation. Its tab gets the 'updated' dot.
    const n = Number(m.index), v = views.get(String(m.view));
    if (!Number.isInteger(n) || n < 1) return;
    lightKey(n);
    if (v && selectedName() !== v.body.name) markUpdated(v, true);
  }
  else if (m.type === "stage:answer") {
    setFollow(true); spot = null; clearSpots();
    for (const [name, late] of lateFrames) if (late.answer !== answerKey(m.n)) lateFrames.delete(name);
    if (lateFront && lateFront.answer !== answerKey(m.n)) lateFront = null;
  }
  else if (m.type === "stage:zoom") {
    const z = Number(m.zoom);
    if (z >= 0.5 && z <= 3) document.documentElement.style.zoom = z === 1 ? "" : String(z);
  }
  else if (m.type === "stage:theme") {
    const theme = m.theme === "dark" ? "dark" : "light";
    if (document.documentElement.dataset.theme === theme) return;
    document.documentElement.dataset.theme = theme;
    for (const f of document.querySelectorAll("iframe.frame")) themeFrame(f);
    redrawDiagrams();
  }
  else if (m.type === "stage:follow") setFollow(!!m.on);
  else if (m.type === "stage:frame") setFrame(String(m.view), Number(m.n), !!m.animate, m.answer);
  else if (m.type === "stage:state") {
    lateFrames.clear(); lateFront = null;  // the whole picture: a late frame or front it still wants is in it again
    for (const [name, n] of Object.entries(m.frames || {})) {
      try { setFrame(name, Number(n), false, m.answer); } catch (e) { console.error("stage:", e); }  // one board never stops the rest
    }
    if (m.front) front(String(m.front), false, m.answer);
    lightKey(Number(m.keys) || 0, false);
  }
  else if (m.type === "stage:point") {
    if (!m.target) { spot = null; clearSpots(); return; }
    if (!follow || !views.has(String(m.view))) return;
    spot = { name: String(m.view), target: m.target };
    clearSpots();
    front(spot.name, false);
    paintSpot(views.get(spot.name));
  }
}

function post(msg) { if (embedded) window.parent.postMessage(msg, "*"); }
function postViews() {
  post({ type: "stage:views", list: [...views.values()].map((v) => ({
    name: v.body.name, title: v.body.title, kind: v.body.kind || kindOf(v.body.source), answer: v.body.answer ?? null })) });
}
if (embedded) {
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent || !e.data || typeof e.data !== "object") return;
    try { onMessage(e.data); } catch (err) { console.warn("stage:", err); }
  });
}
let readySent = false;
function postReady() { if (!readySent) { readySent = true; post({ type: "stage:ready" }); } }

// WC.init runs before the snapshot fetch so nothing that changes during load is missed: its
// opening burst replays every anchor's current state with each delta marked initial:true, and
// a client that already has that state from its own fetch may skip a burst delta whose version
// matches what it already has — but only once it knows what that version is. Until the
// snapshot has rendered we don't, so every delta that lands first goes into `buffered` instead
// of being dropped; once the snapshot is in, we replay `buffered` and only then does `queue`
// exist, so a delta that arrives afterwards joins the same ordered chain a reload can't race.
const versions = new Map();   // anchor -> version already reflected on the page
let queue = null;
let failed = false;           // the snapshot did not load: drop deltas, the retry's snapshot covers them
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

// 'Try again' re-runs this without a page reload: deltas buffer again from the moment it starts.
async function loadSnapshot() {
  const panel = panesEl.querySelector(".empty"), card = panel.querySelector(".emptycard");
  failed = false;
  let snapshot;
  try {
    snapshot = await WC.api.fetchJSON("items");
  } catch (e) {
    failed = true;
    buffered.length = 0;
    panel.classList.add("failed");
    card.querySelector("h2").textContent = "The stage did not load";
    card.querySelector(".msg").textContent = `Could not load the stage: ${e?.message || e}.`;
    if (!card.querySelector(".retry")) card.append(button("Try again", loadSnapshot, "retry"));
    postReady();  // the stage has painted, with its own message and button
    return;
  }
  panel.classList.remove("failed");
  card.querySelector("h2").textContent = "The stage is empty";
  card.querySelector(".msg").textContent = EMPTY_LINE;
  card.querySelector(".retry")?.remove();
  for (const [anchor, item] of Object.entries(snapshot)) {
    versions.set(anchor, item.version);
    if (anchor.startsWith("view:")) upsert(item.body);
    if (anchor === "__layout__") layout = item.body;
  }
  applyLayout();
  live = true;
  postReady();

  queue = Promise.resolve();
  for (const d of buffered.splice(0)) {
    if (alreadyReflected(d)) continue;
    schedule(d.anchor, d.version);
  }
}

window.__stageTest = { escapeLabels, diagramType, splitLines, highlightLines, onMessage, markRange, pairEdits, flowchartKeys,
  frames: () => Object.fromEntries([...views].map(([name, v]) => [name, v.applied])) };
await loadSnapshot();
