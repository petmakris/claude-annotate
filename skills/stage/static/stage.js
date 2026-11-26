// The stage: one tab and one pane per named view, each kept live against its source.
//
// It paints at once: the shell, the snapshot and every view go up before any library has
// loaded. The libraries ship beside this file (vendor/, see VERSIONS.txt) and upgrade what is
// already on screen when they arrive.
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
//     {type:'stage:answer', n, follow}    answer n started playing: unless the reader started it (follow:false)
//                                         following turns on again; a frame or front another answer sent for a
//                                         view not here yet is dropped
//     {type:'stage:rest', views, answer}  answer `answer` has ended: each of these views still on its scene goes
//                                         to the rest frame (the whole board, nothing dimmed); never the view in
//                                         front while following is off
//     {type:'stage:key', view, index}     key point number index (from 1) was just said: it gets the bar
//                                         and a short glow; the Key points tab is never fronted for it
//     {type:'stage:theme', theme}         'light' or 'dark', chosen on the call page
//     {type:'stage:lang', lang}           'en' or 'el': the language the page's words are in; the stage says its own words
//                                         (words.js) in it. A stage opened alone follows the browser's language
//     {type:'stage:zoom', zoom}           how large everything draws: 1 at a desk, more on a TV across the room
//     {type:'stage:follow', on, front}    the call page's switch turned following on or off; with `front` the stage also goes
//                                         back to the board the voice fronted last (a board picked by hand, Key points among them,
//                                         stops holding it)
//     {type:'stage:frame', view, n, animate, answer}  show frame n of the scene answer number `answer` said
//                                         the view with (body.scenes[answer]; without an answer, body.scene),
//                                         clamped to its rest frame, animated only as the next one; never for
//                                         the view in front while following is off
//     {type:'stage:caption', text, answer} the sentence being said ('' clears it): a bubble under the scene part
//                                         being said, else a line at the stage's foot
//     {type:'stage:state', front, frames, keys, answer}  after a jump: every scene's frame as a snap, then the
//                                         front and the key point lit (0: none). It replaces the whole picture:
//                                         frames waiting for a view not here yet are dropped first
//   Stage to talk (to '*': nothing secret in them):
//     {type:'stage:ready'}                once, after the first render
//     {type:'stage:views', list:[{name, title, kind, answer}]}   after every change to the tabs
//     {type:'stage:changed', name, title, isNew}                 a view was created or its source changed
//     {type:'stage:follow', on}                                  following changed here (a tab tap, a chip, a step
//                                                                by hand, Back to the voice, a new answer)
//     {type:'stage:shown', view}                                 this board is in front now, by the voice or by hand
//     {type:'stage:key', key}                                    Space, ArrowLeft or ArrowRight pressed here, on nothing
//                                                                that takes keys: the call page pauses or moves the answer
//     {type:'stage:missing', view}                               a chip asked for a view this stage does not hold
//     {type:'stage:play', view, answer, n}                       Play from here, in a sequence step's popup: the call
//                                                                page plays answer `answer` from the sentence where frame
//                                                                n of its scene for the view begins
//   Stage to the page in a page board (to '*'), once the call page has set a theme:
//     {type:'stage:theme', theme}         on each load and each change. A page from this daemon (a file or
//                                         session board) also gets data-theme on its <html> straight away.
// Unknown types are ignored.
import { applyFrame, beingSaid, settled, stepLabel } from "./scene.js";
import { closeLanesPop, layoutLanes, renderLanes } from "./lanes.js";
import { layoutMap, renderMap } from "./map.js";
import { centreTarget, columnWidths, keepTarget, restScale } from "./fit.js";
import { outlineOf } from "./outline.js";
import { paintScreen, renderScreen } from "./screenboard.js";
import { getLang, setLang, w as wd, wn as wdn } from "./words.js";

const VENDOR = ["highlight.min.js", "marked.min.js", "purify.min.js"]
  .map((f) => new URL("vendor/" + f, import.meta.url).href);

const withTimeout = (p, ms) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error("timed out")), ms))]);
const loadScript = (src) => new Promise((ok, no) => {
  const s = document.createElement("script"); s.src = src;
  s.onload = ok; s.onerror = () => { s.remove(); no(new Error("could not load " + src)); };
  document.head.append(s);
});

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

// ---- Shell ---------------------------------------------------------------------------------

const ICON_PATHS = {
  code: '<path d="M5.5 4 2 8l3.5 4M10.5 4 14 8l-3.5 4"/>',
  diagram: '<rect x="1.5" y="1.5" width="6" height="4.5" rx="1.2"/><rect x="8.5" y="10" width="6" height="4.5" rx="1.2"/><path d="M4.5 6v3a1.5 1.5 0 0 0 1.5 1.5h2.5"/>',
  table: '<rect x="1.5" y="2.5" width="13" height="11" rx="1.6"/><path d="M1.5 6.5h13M6 6.5v7"/>',
  page: '<path d="M3.5 1.5h6l3 3v10h-9z"/><path d="M9.5 1.5v3h3M5.5 8.5h5M5.5 11h5"/>',
  change: '<path d="M4.5 2v6M1.5 5h6M8.5 12.5h6"/>',
  points: '<path d="M6 4h8M6 8h8M6 12h8"/><circle cx="2.6" cy="4" r=".9"/><circle cx="2.6" cy="8" r=".9"/><circle cx="2.6" cy="12" r=".9"/>',
  screen: '<rect x="1.5" y="2" width="13" height="9" rx="1.4"/><path d="M6 14h4M8 11v3"/><rect x="4" y="4.5" width="4" height="3" rx=".6"/>',
  scene: '<rect x="1.5" y="2.5" width="5.5" height="5" rx="1.2"/><rect x="9" y="2.5" width="5.5" height="5" rx="1.2"/><rect x="1.5" y="10" width="13" height="3.5" rx="1.2"/>',
};
const icon = (kind) => `<svg class="ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[kind] || ICON_PATHS.page}</svg>`;
const kindOf = (src) => (src.type !== "inline" ? "page" : src.format === "visual" ? "diagram"
  : src.format in ICON_PATHS ? src.format : "page");

const WC = window.WebCompanion;
const root = document.querySelector("[data-wc-root]") || document.body;
const embedded = window.parent !== window;
root.innerHTML = `<div class="stage">
  <div class="tabbar"><div class="tabnav" role="group" aria-label="${wd("boards")}" hidden>
      <button type="button" class="nb navbtn prev" aria-label="${wd("board.prev")}"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg></button>
      <button type="button" class="nb navbtn next" aria-label="${wd("board.next")}"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg></button>
      <button type="button" class="pos" aria-haspopup="true" aria-expanded="false" aria-label="${wd("board.all")}"><span class="tabpos"></span><span class="posdot" hidden></span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
    </div>
    <button type="button" class="follow" title="${wd("back.voice")}" aria-label="${wd("back.voice")}" hidden>${wd("back.voice")}</button>
    <div class="boards" hidden><h4>${wd("boards")}</h4><nav class="tabs" role="tablist" aria-label="${wd("stage.label")}" aria-orientation="vertical"></nav></div></div>
  <div class="panes"><div class="empty"><div class="emptycard">
    <h2>${wd("empty.title")}</h2><p class="msg">${wd("empty.line")}</p>
    <div class="tiles">${["code", "diagram", "table", "page"].map((k) =>
      `<span class="tile">${icon(k)}<span>${wd("kind." + k)}</span></span>`).join("")}</div>
  </div></div></div>
  <div class="caption" hidden></div>
  <div class="stopcard" role="group" aria-label="${wd("stop.group")}" hidden></div>
  <div class="spop" role="dialog" hidden></div>
</div>`;
const tabsEl = root.querySelector(".tabs"), panesEl = root.querySelector(".panes");
const navEl = root.querySelector(".tabnav"), boardsEl = root.querySelector(".boards"), posEl = root.querySelector(".pos");
const followEl = root.querySelector(".follow"), captionEl = root.querySelector(".caption"), stopEl = root.querySelector(".stopcard");
const spopEl = root.querySelector(".spop");
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const views = new Map();            // name -> {body, tab, pane, filled, stale, renderSeq, changedAt, snap}
let layout = { order: [], front: null };
let live = false;                   // the first snapshot is in: from here a change is news
let follow = true;                  // embedded: boards come to the front as the voice reaches them
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const narrow = () => matchMedia("(max-width: 600px)").matches;
// A board whose words are Greek is marked lang="el": the browser then drops the tonos from a Greek capital
// (text-transform: uppercase), as Greek is written, and the stylesheet gives it Greek-fit heads.
const GREEK = /[\u0370-\u03ff\u1f00-\u1fff]/;
const langOf = (src) => (src.type === "inline" && GREEK.test(JSON.stringify(src)) ? "el" : "");
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
  if (src.format === "table") return wdn("meta.table", tableRows(src.body));
  if (src.format === "change") return `Change · ${src.path} · +${src.added} −${src.removed}` + (src.rev ? ` · since ${src.rev}` : "");
  if (src.format === "points") return wdn("meta.points", src.items.length);
  if (src.format === "diagram") return "Mermaid source";
  if (src.format === "scene") return "Scene · " + wdn("meta.parts", (src.parts || []).length);
  if (src.format === "visual") {
    const names = { sequence: "Sequence diagram", map: "Architecture map", bars: "Comparison chart", graph: "Graph", flowchart: "Flowchart" };
    const t = String(src.tool || "");
    return names[t] || (t ? t[0].toUpperCase() + t.slice(1) : "Visual");
  }
  if (src.format === "screen") {
    const n = (src.screens || []).reduce((a, s) => a + (s.steps || []).length, 0);
    return `Screen · ${wdn("meta.parts", n)} · ${src.spec}`;
  }
  return "Board";
}

function ago(t) {
  const s = (Date.now() - t) / 1000;
  if (s < 60) return wd("ago.now");
  if (s < 3600) return wd("ago.min", { n: Math.floor(s / 60) });
  const h = Math.floor(s / 3600);
  return h < 24 ? wdn("ago.hour", h) : wd("ago.day", { n: Math.floor(h / 24) });
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

// A board with one step, or none, has nothing to step through: its header has no step control ("All shown" over a board with
// nothing to show one by one is noise, and on a phone a second row of the pane's short height).
function hasSteps(v) {
  const all = [v.body.scene, ...Object.values(v.body.scenes || {})].filter(Boolean);
  return all.some((sc) => (sc.steps || 0) > 1);
}

function header(v) {
  const { source: src, caption } = v.body;
  const h = document.createElement("header"); h.className = "phead";
  // One row: the title, with what the board is and when it changed in a tooltip, then its steps and buttons.
  h.innerHTML = `<div class="prow"><div class="vhead" tabindex="0">${icon(kindOf(src))}<h2 class="vtitle"></h2>
    <div class="vtip" role="tooltip"><p class="vmeta"><span></span></p><span class="vage"></span></div></div><div class="pbtns"></div></div>`;
  h.querySelector(".vtitle").textContent = shownTitle(v);
  const meta = h.querySelector(".vmeta span");
  if (src.type === "inline" && src.format === "change") {
    meta.innerHTML = `Change · ${esc(src.path)} · <b class="plus">+${+src.added}</b> <b class="minus">−${+src.removed}</b>` +
      (src.rev ? ` · since ${esc(src.rev)}` : "");
  } else meta.textContent = metaText(src);
  if (v.body.answer && !(src.type === "inline" && src.format === "points")) meta.append(wd("from.answer", { n: +v.body.answer }));
  if (hasSteps(v)) {
    const repairs = +(painted(v)?.scene.repairs) || 0;
    if (repairs) meta.append(wdn("repairs", repairs));
    const bar = document.createElement("span"); bar.className = "stepbar";
    const back = button("", () => stepBy(v, -1), "stepback"), next = button("", () => stepBy(v, 1), "stepnext");
    back.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>`; next.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>`;
    // the middle is a button too: it steps on, and from "All shown" starts the steps again
    const step = document.createElement("button"); step.type = "button"; step.className = "vstep";
    step.onclick = () => { const sc = sceneOf(v) || painted(v)?.scene; if (sc) stepBy(v, (v.frame ?? sc.rest) >= sc.rest ? -sc.rest : 1); };
    back.setAttribute("aria-label", wd("step.prev")); next.setAttribute("aria-label", wd("step.next"));
    back.title = wd("step.prev"); next.title = wd("step.next");
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
    a.className = "btn sm open"; a.target = "_blank"; a.rel = "noopener"; a.textContent = wd("open");
    a.href = frameUrl(src, v.body.rev);
    btns.append(a);
  } else if (["code", "table", "diagram", "change", "points", "visual"].includes(src.format)) {
    const text = () => src.format === "code" ? src.lines.join("\n") : src.format === "change" ? unifiedText(src)
      : src.format === "points" ? src.items.map((it) => `${it.n}. ${it.text}`).join("\n")
      : src.format === "visual" ? JSON.stringify(src.spec, null, 2) : src.body;
    const copy = button(wd("copy"), async () => {
      copy.textContent = await copyText(text()).then(() => wd("copied"), () => wd("copy.failed"));
      clearTimeout(copy._t); copy._t = setTimeout(() => { copy.textContent = wd("copy"); }, 1500);
    });
    btns.append(copy);
  }
  if (src.type === "inline" && (src.format === "code" || src.format === "change")) {
    const wrap = button(wd("wrap"), () => {
      const on = wrap.getAttribute("aria-pressed") !== "true";
      store.set("stage.wrap", on ? "1" : "0");
      for (const b of panesEl.querySelectorAll(".btn.wrapbtn")) b.setAttribute("aria-pressed", String(on));
      for (const c of panesEl.querySelectorAll(".code.lines-box")) { c.classList.toggle("wrap", on); codeCue(c); }
    }, "wrapbtn");
    wrap.setAttribute("aria-pressed", String(wrapOn()));
    btns.append(wrap);
  }
  return h;
}

function wrapOn() {
  const saved = store.get("stage.wrap");
  return saved === null ? true : saved === "1";   // wrapped unless the reader turned it off: a cut line is a line not read
}
// A code box that is not wrapped and holds more to the right fades at its right edge, so a cut line is seen to go on.
function watchCut(box) {
  box.addEventListener("scroll", () => codeCue(box), { passive: true });
  if (typeof ResizeObserver === "function") new ResizeObserver(() => codeCue(box)).observe(box);
}
function codeCue(box) {
  const more = !box.classList.contains("wrap") && box.scrollWidth > box.clientWidth + 2 && box.scrollLeft + box.clientWidth < box.scrollWidth - 2;
  box.classList.toggle("cut-right", more);
}

// A one-line note above a fallback, with a visible button when trying again can help.
function note(box, text, retry) {
  const p = document.createElement("p"); p.className = "note";
  p.append(text);
  if (retry) p.append(button(wd("retry"), retry));
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
  paintFrame(v, box);
  requestAnimationFrame(() => codeCue(box));
}

// A line's leading whitespace in columns (a tab is 4), so a wrapped line continues under its first word.
function indentOf(line) {
  let n = 0;
  for (const c of String(line)) { if (c === " ") n++; else if (c === "\t") n += 4 - (n % 4); else break; }
  return Math.min(n, 40);
}

// On first show, the first marked line sits about a third of the way down.
function scrollToMark(box) {
  if (box.querySelector(".ln.k-focus")) return;  // the lines being spoken about win
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
      else if (r.old != null) row.dataset.old = r.old;  // a removed line, keyed old:<n>
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
  paintFrame(v, box);
  requestAnimationFrame(() => codeCue(box));
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
    const cap = document.createElement("p"); cap.className = "kcap"; cap.dataset.answer = answer || ""; cap.textContent = answer ? wd("points.cap", { n: answer }) : wd("points.earlier");
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

// A number as a column of numbers holds it: a sign or ~, a currency sign before, a unit or k/M/B/x after.
const NUM = /^[-+~≈<>≤≥]?\s?(?:[$€£¥]\s?)?[-+]?\d[\d.,\u202f ]*\s?(?:%|ms|µs|s|min|h|d|KB|MB|GB|TB|[kKMBT]|[x×]|€|\$|£|¥|pp|bps)?\+?$/;

// Markdown as the stage shows it: sanitized; a relative link or image read against the file it came
// from; a link out opening in a new tab, so the stage is never navigated away; headings given ids
// (prefixed, never clashing with the page's own) that the document's #links scroll to.
const slug = (t) => "md-" + String(t).trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-");
// A table board's cells hold text and a small markdown set only: raw HTML is shown as written (List<T> is `List<T>`,
// not a tag the sanitizer would drop), except <br>, a line break.
const BOARD_TAGS = ["table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col", "code", "strong", "em", "b", "i",
  "del", "a", "br", "p", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr"];
function boardHtml(text) {
  const renderer = new marked.Renderer();
  renderer.html = (h) => (/^<br\s*\/?>$/i.test(String(h.text ?? h).trim()) ? "<br>" : esc(String(h.text ?? h)));
  return DOMPurify.sanitize(marked.parse(text, { renderer }), { ALLOWED_TAGS: BOARD_TAGS, ALLOWED_ATTR: ["href", "align", "title", "colspan", "rowspan"] });
}
function markdownInto(box, text, base = null, board = false) {
  box.innerHTML = board ? boardHtml(text) : DOMPurify.sanitize(marked.parse(text), { FORBID_TAGS: ["form", "meta", "iframe", "style", "base"] });
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

// ---- The table board -----------------------------------------------------------------------
// The whole table is drawn once, at its final size and place (fixed layout, column widths set from the text), and
// never changes shape: what is not said yet is dim, what has been said is plain, what is being said is lit by colour
// and weight only. A row, several rows, a column or a pair of cells can be lit. Rows are numbered across every table
// of the board, as the server counts them (row#<n>, cell#<row>.<column>, col#<column> or col#<table>.<column>).
const TONES = [[/^(?:✓|✔|✅|☑)/, "ok"], [/^(?:✗|✘|✖|❌|⛔)/, "bad"], [/^(?:⚠|🟡)/, "warn"]];
const FIT_CHARS = 50;  // a phone wraps a grid whose columns need no more than this many characters across, else it scrolls sideways
function shapeBoard(box) {
  const tables = [...box.querySelectorAll("table")];
  tables.forEach((table, t) => {
    const wrap = document.createElement("div"); wrap.className = "tablewrap board";
    table.before(wrap); wrap.append(table);
    const heads = [...table.querySelectorAll("thead th")];
    const rows = [...table.querySelectorAll("tbody tr")].map((tr) => [...tr.children]);
    const cols = Math.max(heads.length, ...rows.map((r) => r.length), 0);
    table.dataset.t = String(t + 1);
    heads.forEach((th, i) => { th.dataset.c = String(i + 1); });
    for (const r of rows) r.forEach((td, i) => { td.dataset.c = String(i + 1); td.dataset.label = (heads[i]?.textContent || "").trim(); });  // the name a phone's row card gives each cell
    const col = (i) => rows.map((r) => r[i]).filter(Boolean);
    const text = (td) => td.textContent.trim();
    const widths = [], phone = [], scrolled = []; let need = 0;
    for (let i = 0; i < cols; i++) {
      const cells = col(i).map(text).filter(Boolean);
      const numeric = cells.length > 0 && cells.filter((x) => NUM.test(x)).length >= Math.ceil(cells.length * 0.75);
      for (const td of [...col(i), heads[i]]) if (td && numeric) td.classList.add("num");
      const longest = Math.max(0, ...cells.map((x) => x.length)), head = (heads[i]?.textContent || "").trim().length;
      widths.push(Math.min(40, Math.max(6, Math.ceil(head * 1.1), Math.min(longest, 40))) + 4.5);  // its text, and the cell's padding
      // a phone wraps the words, so what a column needs is its longest word, with a share of its text beyond that
      const word = Math.max(0, ...cells.flatMap((x) => x.split(/\s+/).map((w) => w.length)), Math.ceil((heads[i]?.textContent || "").trim().length * 0.85));
      phone.push(Math.min(word, 22) + 2.5 + Math.sqrt(Math.min(longest, 60)));
      need += Math.min(word, 22) + 2.5;
      scrolled.push(Math.max(8, Math.min(word, 22) + 3, Math.min(longest, 26) + 3));  // a sideways grid's column, in characters
      widths[i] = Math.max(widths[i], word * 1.05 + 4.5);
    }
    if (col(0).length && col(0).every((td) => text(td).length <= 28)) {
      for (const td of [...col(0), heads[0]]) td?.classList.add("key");
    }
    wrap.classList.toggle("sticky-key", col(0).length > 0 && col(0).every((td) => td.classList.contains("key")));
    for (const r of rows) for (const td of r) for (const [re, tone] of TONES) if (re.test(text(td))) td.classList.add("tone-" + tone);
    // columns share the width by their text, never by what is lit: nothing moves when a row is said
    const sum = widths.reduce((a, b) => a + b, 0) || 1;
    const group = document.createElement("colgroup");
    const psum = phone.reduce((a, b) => a + b, 0) || 1;
    widths.forEach((w, i) => {
      const c = document.createElement("col");
      c.style.setProperty("--w", (100 * w / sum).toFixed(2) + "%"); c.style.setProperty("--wp", (100 * phone[i] / psum).toFixed(2) + "%");
      c.dataset.w = String(w / sum); c.dataset.wp = String(phone[i] / psum);   // the shares wordFloors turns into px
      c.style.setProperty("--wn", scrolled[i].toFixed(1));
      group.append(c);
    });
    table.prepend(group);
    const ch = Math.round(sum);   // narrow tables size to their text, centred; wide ones span the stage
    wrap.style.setProperty("--tw", ch + "ch");
    wrap.classList.toggle("span", cols >= 6);
    table.style.setProperty("--tws", String(Math.round(scrolled.reduce((a, b) => a + b, 0))));
    table.dataset.fit = need <= FIT_CHARS ? "fit" : "scroll";  // the phone's form: a compact grid, or a sideways one
    wrap.addEventListener("scroll", () => scrollCue(wrap), { passive: true });
    wordFloors(table, wrap);
    if (typeof ResizeObserver === "function") {
      let was = [0, 0];
      const ro = new ResizeObserver(() => {
        const now = [wrap.clientWidth, box.clientWidth];
        if (now[0] && (Math.abs(now[0] - was[0]) > 1 || Math.abs(now[1] - was[1]) > 1)) { was = now; refit(box); }
      });
      ro.observe(wrap); ro.observe(box);
    }
  });
}
// A table at rest on a wide desk screen is drawn larger, to about 70 % of the pane's width and at most 1.6 times its size
// on the screen (the TV layout's zoom counts towards that): `--up` on the board's box, which the stylesheet turns into
// the text's size and the table's width. Never while a row is said (nothing moves between the steps), never on a phone,
// never for a board of several tables. The column floors are measured again at the size it is drawn at (wordFloors).
function restFit(box) {
  const wrap = box.querySelector(":scope > .tablewrap");
  if (!wrap) return;
  wrap.style.removeProperty("--up");
  const phone = typeof matchMedia === "function" && matchMedia("(max-width:600px)").matches;
  if (!box.classList.contains("g-rest") || phone || box.querySelectorAll(".tablewrap").length !== 1) return;
  const body = box.closest(".pbody"), zoom = +document.documentElement.style.getPropertyValue("--z") || 1;
  const up = restScale({ natural: wrap.offsetWidth, height: wrap.offsetHeight, pane: box.clientWidth, paneHeight: body ? body.clientHeight : 0, zoom });
  if (up > 1) wrap.style.setProperty("--up", String(up));
}
function refit(box) {
  restFit(box);
  for (const wrap of box.querySelectorAll(".tablewrap")) { const table = wrap.querySelector("table"); if (table) wordFloors(table, wrap); scrollCue(wrap); }
}

// A column is never narrower than its longest word, so a word never breaks across lines (no `Latenc/y`): each column's
// floor is that word measured in the cell's own font (bold, as a lit row is; a header in capitals and its letter-spacing)
// plus the cell's padding, shared out by the column's text as before for the rest. When the floors do not fit the board's
// width, the text of the whole table is set smaller (down to 72 %); under that the table scrolls sideways, still unbroken.
let measureCtx;
function wordFloors(table, wrap) {
  measureCtx ||= document.createElement("canvas").getContext?.("2d");
  const cols = [...table.querySelectorAll(":scope > colgroup > col")];
  if (!measureCtx || !cols.length) return;
  const word = cols.map(() => 0), pad = cols.map(() => 0);
  const up = +wrap.style.getPropertyValue("--up") || 1;   // a table at rest on a wide screen is drawn larger (restFit)
  const lang = GREEK.test(table.textContent) ? "el" : undefined;   // as the pane is marked, so a Greek head is measured without its tonos
  for (const td of table.querySelectorAll("th, td")) {
    const i = (+td.dataset.c || 0) - 1;
    if (i < 0 || i >= cols.length) continue;
    const cs = getComputedStyle(td), size = parseFloat(cs.fontSize) || 14;
    const sc = (+wrap.style.getPropertyValue("--tf") || 1) * up;   // the measure is of the text at its own size, whatever it is drawn at
    pad[i] = Math.max(pad[i], (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0) + 2);
    const walker = document.createTreeWalker(td, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const host = n.parentElement, hs = host === td ? cs : getComputedStyle(host), fs = (parseFloat(hs.fontSize) || size) / sc;
      measureCtx.font = `${Math.max(600, +hs.fontWeight || 400)} ${fs}px ${hs.fontFamily}`;
      const track = (parseFloat(hs.letterSpacing) || 0) / sc, caps = hs.textTransform === "uppercase";
      for (const w of n.nodeValue.split(/\s+/)) {
        if (!w) continue;
        const text = caps ? w.toLocaleUpperCase(lang) : w;
        word[i] = Math.max(word[i], measureCtx.measureText(text).width + track * text.length + (host === td ? 0 : 12));
      }
    }
  }
  const avail = wrap.clientWidth - 2, padSum = pad.reduce((a, b) => a + b, 0), wordSum = word.reduce((a, b) => a + b, 0);
  if (!avail || !wordSum) return;
  const tf = padSum + wordSum * up <= avail ? 1 : Math.max(0.72, Math.min(1, (avail - padSum) / (wordSum * up)));
  wrap.style.setProperty("--tf", tf.toFixed(3));
  const floors = word.map((w, i) => w * tf * up + pad[i]);
  cols.forEach((c, i) => c.style.setProperty("--min", floors[i].toFixed(1) + "px"));
  const total = floors.reduce((a, f) => a + f, 0);
  table.style.minWidth = total > avail ? Math.ceil(total) + "px" : "";   // the floors do not fit: the table scrolls, unbroken
  // the columns' widths in px, floors held (fit.js): a calc with a % and a px on a <col> is read as `auto`
  const phone = (typeof matchMedia === "function" && matchMedia("(max-width:600px)").matches) && table.dataset.fit === "fit";
  const px = columnWidths(cols.map((c) => +(phone ? c.dataset.wp : c.dataset.w) || 0), floors, Math.max(avail + 2, total));
  cols.forEach((c, i) => { c.style.width = px[i] + "px"; });
}
// A table taller than its board keeps its header and shows it goes on: the foot fades until the end is reached.
// A table taller than its board says how much is below: the foot fades, and a pill under it counts the rows out of sight
// ("2 more rows") and scrolls them in when pressed, since a fade alone is easy to miss on a short phone pane.
function scrollCue(wrap) {
  const more = wrap.scrollHeight > wrap.clientHeight + 2;
  const atEnd = !more || wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 2;
  wrap.classList.toggle("scrolls", more);
  wrap.classList.toggle("at-end", atEnd);
  const host = wrap.parentElement;
  let pill = host?.querySelector(":scope > .more-rows");
  const out = atEnd ? 0 : [...wrap.querySelectorAll("tbody tr")].filter((tr) => tr.getBoundingClientRect().bottom > wrap.getBoundingClientRect().bottom + 2).length;
  if (!out) { pill?.remove(); return; }
  if (!pill) {
    pill = document.createElement("button"); pill.type = "button"; pill.className = "more-rows";
    pill.onclick = () => wrap.scrollBy({ top: wrap.clientHeight * 0.8, behavior: reduced() ? "auto" : "smooth" });
    host.append(pill);
  }
  pill.textContent = "↓ " + wdn("rows.more", out);
  pill.style.bottom = Math.max(6, host.getBoundingClientRect().bottom - wrap.getBoundingClientRect().bottom + 8) + "px";
}

function paintTable(v, box, src) {
  if (!hasMarkdown()) { box.innerHTML = `<pre>${esc(src.body)}</pre>`; return; }
  markdownInto(box, src.body, null, true);
  shapeBoard(box);
  for (const t of box.querySelectorAll("table")) if (!t.querySelector("caption")) {  // the title names the table for a screen reader; never drawn
    const c = document.createElement("caption"); c.className = "sr-cap"; c.textContent = shownTitle(v); t.insertBefore(c, t.firstChild);
  }
  box.classList.add("grid", "g-rest");  // a table board: the grid, its row, rows, column or cells being said lit; whole until a frame steps it
  box.addEventListener("click", (e) => tapRow(v, box, e));
  pulseDiff(v, box, "rows", [...box.querySelectorAll("tbody tr")].map((tr) => [...tr.querySelectorAll("td, th")].map((c) => c.textContent).join("\u001f")));  // a unit separator: "a|12" is not "a1|2"
  paintFrame(v, box);
  refit(box);
}

// A row of a table board tapped: its first cell names it, Ask about this starts the question about it in the call's
// text field, and Play from here goes to the sentence that says the row when an answer does. A row no answer says
// offers only the question, and says so.
function tapRow(v, box, e) {
  if (e.target.closest?.("a[href]")) return;
  const tr = e.target.closest?.("tbody tr");
  if (!tr || !box.contains(tr)) { closePop(); return; }
  const n = [...box.querySelectorAll("tbody tr")].indexOf(tr) + 1, key = "row#" + n;
  const name = (tr.children[0]?.textContent || "").trim().replace(/\s+/g, " ") || wd("row.n", { n });
  const acts = [button(wd("ask.about"), () => { closePop(); post({ type: "stage:ask", text: `About "${name}": ` }); }, "pri")];
  const said = playKey(v, key, true);
  if (said) acts.push(button(wd("play.here"), () => { closePop(); playKey(v, key); }));
  openPop(name.charAt(0).toUpperCase() + name.slice(1), said ? null : wd("not.said"), acts, tr);
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
  if (what === "rows") {
    // A table is diffed by row text, not by place: an inserted or removed row moves the rows after it
    // without changing them. A row glows when it is added or edited; an unchanged duplicate row is matched once each.
    const left = new Map();
    for (const t of prev) left.set(t, (left.get(t) || 0) + 1);
    now.forEach((t, i) => { const n = left.get(t) || 0; if (n) left.set(t, n - 1); else restart(els[i], "changed"); });
    return;
  }
  now.forEach((t, i) => { if (prev[i] !== t) restart(els[i], "changed"); });
}
function restart(el, cls) {
  if (!el) return;
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
  el.addEventListener("animationend", () => el.classList.remove(cls), { once: true });
}

// ---- Boards ---------------------------------------------------------------------------------

// Returns the box at once. Anything that waits (libraries) fills it later, and only
// while the view still shows the body it started from: `seq` is the fill it belongs to.
function renderInline(v, seq) {
  const src = v.body.source, box = document.createElement("div");
  const current = () => v.renderSeq === seq && box.isConnected;
  const retryLibs = () => { libsP = null; fillPane(v); };
  if (src.format === "code") {
    box.className = "code lines-box" + (wrapOn() ? " wrap" : "");
    watchCut(box);
    paintCode(v, box, src);
    if (!window.hljs) libsReady().then(() => {
      if (!current()) return;
      if (window.hljs) paintCode(v, box, src); else note(box, wd("note.highlight"), retryLibs);
    });
  } else if (src.format === "change") {
    box.className = "code lines-box change" + (wrapOn() ? " wrap" : "");
    watchCut(box);
    paintChange(v, box, src);
    if (!window.hljs) libsReady().then(() => {
      if (!current()) return;
      if (window.hljs) paintChange(v, box, src); else note(box, wd("note.highlight"), retryLibs);
    });
  } else if (src.format === "points") {
    box.className = "points";
    paintPoints(v, box, src);
  } else if (src.format === "visual" && src.tool === "sequence") {
    // A sequence unfolds with the voice as lanes: every arrow carries its sentence, no numbered key.
    box.className = "visual lanes";
    renderLanes(box, src.spec, embedded, { refs: src.refs, play: (step, dry) => playStep(v, step, dry) });
    requestAnimationFrame(() => { if (current()) paintFrame(v, box); });
  } else if (src.format === "visual" && ["map", "bars", "graph"].includes(src.tool)) {
    // An architecture map, a bars board and a graph board are drawn on the server (map_svg, bars_svg and graph_svg,
    // keyed for the frames) and made safe again here.
    box.className = "visual vzmap" + (src.tool === "map" ? "" : " vz" + src.tool);
    paintVzMap(v, box, src);
    if (!window.DOMPurify) libsReady().then(() => {
      if (!current()) return;
      if (window.DOMPurify) paintVzMap(v, box, src); else note(box, wd("note.map"), retryLibs);
    });
  } else if (src.format === "visual" && src.tool === "flowchart") {
    // A flowchart is a map the stage draws itself: ghosts first, lit part by part with the voice.
    box.className = "visual map";
    renderMap(box, src.spec, embedded);
    requestAnimationFrame(() => { if (current()) { paintFrame(v, box); if (!hasScene(v)) layoutMap(box, null); } });
  } else if (src.format === "scene" && src.sandboxed) {
    // A scene with a script runs whole in a sealed frame; the frames reach its parts by message.
    box.className = "visual scene sandboxed";
    paintSandbox(v, box, src);
  } else if (src.format === "scene") {
    // A scene comes in part by part with the voice: its parts are keyed for the frames to show and light.
    box.className = "visual scene";
    paintScene(v, box, src);
    if (!window.DOMPurify) libsReady().then(() => {
      if (!current()) return;
      if (window.DOMPurify) paintScene(v, box, src); else note(box, wd("note.scene"), retryLibs);
    });
  } else if (src.format === "screen") {
    // A spotlight: one screen at a time, the part being said lit and explained beside it (screenboard.js).
    const imageUrl = (path) => `${WC.api.BASE}mounts/${encodeURIComponent(src.mount)}/` +
      String(path).split("/").map(encodeURIComponent).join("/");
    renderScreen(box, src, { imageUrl, embedded });
    if (!window.DOMPurify) libsReady().then(() => { if (current() && window.DOMPurify) { renderScreen(box, src, { imageUrl, embedded }); paintFrame(v, box); } });
    requestAnimationFrame(() => { if (current()) paintFrame(v, box); });
  } else if (src.format === "diagram") {
    // A Mermaid board saved before the stage stopped drawing Mermaid: its source, as written.
    box.className = "md legacy";
    const said = document.createElement("p"); said.className = "note";
    said.textContent = wd("note.mermaid");
    box.append(said, sourceFrame(src.body));
  } else {
    box.className = "md";
    paintTable(v, box, src);
    if (!hasMarkdown()) libsReady().then(() => {
      if (!current()) return;
      if (hasMarkdown()) paintTable(v, box, src); else note(box, wd("note.table"), retryLibs);
    });
  }
  // The board is one figure named by its title; its text is the table's cells, the parts and the arrows list inside it.
  box.setAttribute("role", "figure"); box.setAttribute("aria-label", shownTitle(v));
  return box;
}

// A scene's HTML, sanitized: no script, form, frame, style or link survives, and no handler attribute.
// Each part (data-part) becomes a key the frames reveal and light.
function paintScene(v, box, src) {
  if (!window.DOMPurify) return;
  box.innerHTML = DOMPurify.sanitize(src.html, { FORBID_TAGS: ["form", "meta", "iframe", "style", "base", "script", "link", "object", "embed"] });
  for (const el of box.querySelectorAll("[data-part]")) el.dataset.key = "part:" + el.dataset.part;
  for (const a of box.querySelectorAll("a[href]")) { a.target = "_blank"; a.rel = "noopener"; }
  box.onclick = (e) => tapScene(v, e);
  requestAnimationFrame(() => { if (box.isConnected) paintFrame(v, box); });
}

// An architecture map, as map_svg drew it on the server: its words are escaped text there, and DOMPurify (SVG only)
// takes out anything else before it goes in, so a forged view can bring no markup. Every part carries its key
// (box:, zone:, edge:, route:), which the frames show and light.
function paintVzMap(v, box, src) {
  if (!window.DOMPurify) return;
  box.innerHTML = DOMPurify.sanitize(String(src.svg || ""), { USE_PROFILES: { svg: true } });
  const svg = box.querySelector("svg.vz");
  if (svg) {
    svg.classList.add("outline");  // what is still to come is an outline, as in the player
    for (const el of svg.querySelectorAll("[marker-end]")) el.dataset.mk = el.getAttribute("marker-end");
  }
  if (svg) svg.after(readingOf(src.reading));
  box.onclick = (e) => tapMap(v, e);
  requestAnimationFrame(() => { if (box.isConnected) paintFrame(v, box); });
}
// What a screen reader says of a drawn board: its arrows (map, graph) or rows (bars), one line each, in a list kept out of
// sight but in the accessibility tree (the .vz-reading rule). The server made the items (reading.py); the connecting words
// are the stage's own, in the page's language.
function readingLine(it) {
  if (it.kind === "state") return wd("read.state." + it.state, { label: it.label });
  if (it.kind === "bar") return it.note ? wd("read.bar.note", it) : wd("read.bar", it);
  if (it.kind === "threshold") return wd("read.threshold", it);
  const key = it.kind === "link" ? "read.link" : "read.edge";
  return wd(it.label ? key + ".label" : key, it) + (it.dashed ? wd("read.dashed") : "");
}
function readingOf(list) {
  const ul = document.createElement("ul"); ul.className = "vz-reading";
  if (!list || !Array.isArray(list.items) || !list.items.length) { ul.hidden = true; return ul; }
  ul.setAttribute("aria-label", wd(list.title === "values" ? "read.values" : "read.arrows"));
  ul.replaceChildren(...list.items.map((it) => { const li = document.createElement("li"); li.textContent = readingLine(it); return li; }));
  return ul;
}
// After a frame: the parts being said take the accent (vz.css's `now`, with the accent's arrowhead), and while
// the voice follows the request (a route step shown before the rest frame) the map is in route mode: the route's
// arrows show, the structure arrows off it go, the parts it never touches are dimmed, and so are the parts it
// reaches only later. Returns the parts said.
function layoutVzMap(box, scene, n) {
  const svg = box.querySelector("svg.vz");
  if (!svg) return [];
  const last = scene.frames.length - 1, frame = scene.frames[Math.max(0, Math.min(n, last))];
  const cur = new Set(beingSaid(scene, n));
  const steps = n < scene.rest ? frame.show.filter((k) => k.startsWith("route:")).map((k) => +k.slice(6)) : [];
  const at = steps.length ? Math.max(...steps) : null;  // how far the request has come
  svg.classList.toggle("mode-route", at !== null);
  if (svg.dataset.vz === "graph") layoutGraph(box, svg, frame, n < scene.rest);
  const pointed = svg.classList.contains("tall") && n < scene.rest ? ["before", "after"].find((m) => (frame.focus || []).includes("mode:" + m)) : null;
  const on = svg.querySelector('marker[id$="-on"]')?.id, said = [];
  for (const el of svg.querySelectorAll("[data-key]")) {
    const now = cur.has(el.dataset.key);
    el.classList.toggle("now", now);
    el.classList.toggle("r-later", at !== null && el.dataset.r !== undefined && +el.dataset.r > at);  // the request is not there yet
    if (now) said.push(el);
    if (!el.dataset.mk) continue;
    const head = now && on ? `url(#${on})` : el.dataset.mk;
    if (el.dataset.marker) el.dataset.marker = head;  // drawing in: its head comes back when the line is drawn
    else el.setAttribute("marker-end", head);
  }
  const group = pointed && svg.querySelector(`g[data-orient="tall"] > g[data-frame="${pointed}"]`);
  return withEnds(svg, group ? [...said, group] : said);
}
// An arrow lit on a drawn map is kept in view with the two boxes (or nodes) it joins, not on its own.
function withEnds(svg, els) {
  const out = [...els];
  for (const el of els) {
    const m = /^edge:(.+)->(.+)#\d+$/.exec(el.dataset.key || "");
    if (m) {
      for (const id of [m[1], m[2]]) for (const kind of ["box", "node"])
        for (const e of svg.querySelectorAll(`[data-key="${kind}:${CSS.escape(id)}"]`)) if (!out.includes(e)) out.push(e);
    } else if (el.tagName === "path" && el.classList.contains("ar") && el.getTotalLength && el.getScreenCTM()) {
      // a route step's arrow names no boxes: the boxes its two ends touch
      const ctm = el.getScreenCTM(), len = el.getTotalLength();
      const ends = [0, len].map((d) => { const p = el.getPointAtLength(d); return [p.x * ctm.a + p.y * ctm.c + ctm.e, p.x * ctm.b + p.y * ctm.d + ctm.f]; });
      for (const e of svg.querySelectorAll('rect.bx[data-key^="box:"]')) {
        const r = e.getBoundingClientRect();
        if (!out.includes(e) && ends.some(([x, y]) => x >= r.left - 6 && x <= r.right + 6 && y >= r.top - 6 && y <= r.bottom + 6)) out.push(e);
      }
    }
  }
  return out;
}
// A graph board: the frame the voice points at (`mode:before`, `mode:after`) keeps the light and the other goes faint, a
// pointed frame alone lights no part, and on a narrow board one frame shows at a time (its own viewBox) with a switch.
function layoutGraph(box, svg, frame, playing) {
  const focus = frame.focus || [], said = ["before", "after"].find((m) => focus.includes("mode:" + m));
  const modes = focus.length > 0 && focus.every((k) => k.startsWith("mode:"));
  svg.classList.toggle("mode-before", playing && said === "before");
  svg.classList.toggle("mode-after", playing && said === "after");
  if (modes) box.classList.remove("k-dim");  // a frame is not a part: nothing else dims
  const two = svg.dataset.frames === "2", narrow = two && box.clientWidth > 0 && box.clientWidth < 640;
  // a graph on a phone is drawn turned (lanes as columns, time down the page) at a scale of 1 or more, so its text stays
  // 11 px or more and it pans down only; before sits above after. A graph saved without that drawing keeps the one-frame switch.
  const tall = box.clientWidth > 0 && box.clientWidth < 640 && !!svg.dataset.vbTallBoth;
  svg.classList.toggle("tall", tall);
  box.classList.toggle("g-tall", tall);
  box.classList.toggle("g-narrow", narrow && !tall);
  if (said) box.dataset.gframe = said;
  if (tall) {
    const tvb = svg.dataset.vbTallBoth;
    svg.setAttribute("viewBox", tvb);
    const cs = getComputedStyle(box);
    svg.style.width = Math.min(+tvb.split(" ")[2], box.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0)) + "px";
    const old = box.querySelector(":scope > .gsw");
    if (old) old.hidden = true;
    return;
  }
  const pick = narrow ? (box.dataset.gframe || "after") : "both";
  const vb = svg.dataset["vb" + pick.charAt(0).toUpperCase() + pick.slice(1)];
  if (vb) svg.setAttribute("viewBox", vb);
  svg.style.width = narrow ? Math.max(box.clientWidth - 32, +vb.split(" ")[2] * 0.75) + "px" : "";
  let sw = box.querySelector(":scope > .gsw");
  if (narrow && !sw) {
    sw = document.createElement("div");
    sw.className = "gsw";
    for (const name of ["before", "after"]) {
      const b = document.createElement("button");
      b.type = "button"; b.dataset.frame = name; b.textContent = name === "before" ? "Before" : "After";
      b.onclick = () => { box.dataset.gframe = name; layoutGraph(box, svg, frame, playing); };
      sw.append(b);
    }
    box.prepend(sw);
  }
  if (sw) { sw.hidden = !narrow; for (const b of sw.children) b.setAttribute("aria-pressed", String(b.dataset.frame === pick)); }
}
// A map wider than its board scrolls sideways: the parts being said are brought to its middle.
function centreAcross(box, els) {
  const shown = els.filter((e) => e.isConnected);
  if (!shown.length || box.scrollWidth <= box.clientWidth + 1) return;
  const b = box.getBoundingClientRect(), rs = shown.map((e) => e.getBoundingClientRect());
  const mid = (Math.min(...rs.map((r) => r.left)) + Math.max(...rs.map((r) => r.right))) / 2 - b.left;
  box.scrollTo({ left: box.scrollLeft + mid - box.clientWidth / 2, behavior: reduced() ? "auto" : "smooth" });
}
// A part of the map tapped: its name, Ask about this, and Play from here when an answer says it.
function tapMap(v, e) {
  const part = e.target.closest("[data-key]:not(.k-hidden)");
  if (!part) { closePop(); return; }
  const key = part.dataset.key, name = mapPartName(v.body.source.spec || {}, key);
  const acts = [button(wd("ask.about"), () => { closePop(); post({ type: "stage:ask", text: `About "${name}": ` }); }, "pri")];
  if (playKey(v, key, true)) acts.push(button(wd("play.here"), () => { closePop(); playKey(v, key); }));
  openPop(name.charAt(0).toUpperCase() + name.slice(1), null, acts, part);
}
function mapPartName(spec, key) {
  const plain = (t) => String(t || "").replace(/`/g, "");
  const [kind, id] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
  const boxes = [];
  const walk = (b) => { boxes.push(b); (b.children || []).forEach(walk); };
  (spec.boxes || []).forEach(walk);
  const box = (bid) => plain(boxes.find((b) => b.id === bid)?.name || bid);
  if (kind === "box") return box(id);
  if (kind === "zone") return plain((spec.zones || [])[+id]?.label || "zone " + id);
  if (kind === "bar") return plain((spec.bars || []).find((b) => b.id === id)?.label || id);
  if (kind === "node") return plain((spec.nodes || []).find((n) => n.id === id)?.label || id);
  if (kind === "route") {
    const cap = ((spec.captions || {}).route || [])[+id - 1];
    const labels = (spec.arrows || []).filter((a) => a.layer === "route" && String(a.r ?? 1) === id && a.label).map((a) => plain(a.label));
    return plain(cap?.title) || labels.join(", ") || "step " + id + " of the request";
  }
  const [from, to] = id.replace(/#\d+$/, "").split("->");
  return `${box(from)} to ${box(to)}`;
}

// A scene with a script runs in a sealed frame: sandbox="allow-scripts" without allow-same-origin, so it reaches
// neither the stage nor its storage, and a policy of default-src 'none' lets it load nothing but the stage's own
// stylesheet and fonts. A small script put in first keys its parts and applies the frames the stage posts.
const SANDBOX_SHIM = `(() => {
  let last = null;
  const key = () => { for (const el of document.querySelectorAll("[data-part]")) el.dataset.key = "part:" + el.dataset.part; };
  const apply = (m) => {
    last = m; key();
    if (m.theme) document.documentElement.dataset.theme = m.theme;
    const show = new Set(m.show), focus = new Set(m.focus), cur = new Set(m.cur);
    for (const el of document.querySelectorAll("[data-key]")) {
      const k = el.dataset.key;
      el.classList.add("k-key");
      el.classList.toggle("k-hidden", !show.has(k));
      el.classList.toggle("k-focus", focus.has(k));
      el.classList.toggle("s-cur", cur.has(k));
    }
    if (document.body) {
      document.body.classList.toggle("k-dim", focus.size > 0);
      document.body.classList.toggle("s-on", cur.size > 0);
      document.body.classList.toggle("s-play", !!m.animate);
    }
    const said = [...document.querySelectorAll(".k-focus, .s-cur")].pop();
    if (said) said.scrollIntoView({ block: "nearest", behavior: m.animate ? "smooth" : "auto" });
  };
  addEventListener("message", (e) => { if (e.source === parent && e.data && e.data.type === "scene:frame") apply(e.data); });
  addEventListener("DOMContentLoaded", () => { key(); if (last) apply(last); parent.postMessage({ type: "scene:ready" }, "*"); });
})();`;
// The frame loads nothing: the stage's stylesheet goes in inline, and its fonts as data: URLs (the frame's origin
// is opaque and fonts are fetched with CORS), each read once. Without them the frame falls back to the system's
// sans-serif and the browser's own look.
const FONTS = [["Inter", "Inter-Variable.woff2", "100 900", ""], ["Inter", "Inter-Greek-Variable.woff2", "100 900",
  "unicode-range:U+0370-0377,U+037A-037F,U+0384-038A,U+038C,U+038E-03A1,U+03A3-03FF;"],
  ["JetBrains Mono", "JetBrainsMono-Variable.woff2", "100 800", ""]];
let fontsP = null;
function fontFaces() {
  const asData = (blob) => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = no; r.readAsDataURL(blob); });
  fontsP ||= Promise.all(FONTS.map(async ([family, file, weight, range]) => {
    const resp = await fetch(new URL("fonts/" + file, import.meta.url));
    if (!resp.ok) throw new Error("font " + file + ": HTTP " + resp.status);
    const url = String(await asData(await resp.blob())).replace(/^data:[^;,]*/, "data:font/woff2");
    return `@font-face{font-family:"${family}";src:url("${url}") format("woff2");font-weight:${weight};font-display:swap;${range}}`;
  })).then((faces) => faces.join("\n"), (e) => { console.warn("stage:", e.message); return ""; });
  return withTimeout(fontsP, 4000).catch(() => "");
}
let sheetP = null;
function stageSheet() {
  sheetP ||= fetch(new URL("stage.css", import.meta.url)).then((r) => (r.ok ? r.text() : ""))
    .then((t) => t.replace(/@font-face\{[^}]*\}/g, ""), () => "");
  return withTimeout(sheetP, 4000).catch(() => "");
}
function paintSandbox(v, box, src) {
  const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; font-src data:; img-src data:";
  const frame = document.createElement("iframe");
  frame.className = "sandbox";
  frame.title = v.body.title || "Scene";
  frame.setAttribute("sandbox", "allow-scripts");
  box.replaceChildren(frame);
  v.sandbox = { frame, last: null };
  Promise.all([fontFaces(), stageSheet()]).then(([faces, sheet]) => {
    const theme = document.documentElement.dataset.theme;
    frame.srcdoc = `<!doctype html><html${theme ? ` data-theme="${theme}"` : ""}${GREEK.test(src.html) ? ' lang="el"' : ""}><head><meta charset="utf-8">`
      + `<meta http-equiv="Content-Security-Policy" content="${esc(policy)}">`
      + `<style>${faces}\n${sheet.replace(/<\/style/gi, "<\\/style")}\nhtml{height:100%}body{height:auto;min-height:100%;background:transparent}[data-part]:not(.k-key){opacity:0}</style>`
      + `<script>${SANDBOX_SHIM}<\/script></head><body class="visual scene sealed">${src.html}</body></html>`;
  });
  requestAnimationFrame(() => { if (box.isConnected) paintFrame(v, box); });
}
// The frame of view v's scene as the sealed frame applies it: what shows, what is lit, what is being said.
function postSandbox(v, msg) {
  const sb = v.sandbox;
  if (!sb) return;
  sb.last = { type: "scene:frame", ...msg, theme: document.documentElement.dataset.theme || null };
  try { sb.frame.contentWindow.postMessage(sb.last, "*"); } catch {}
}
window.addEventListener("message", (e) => {
  const v = e.data && e.data.type === "scene:ready" ? [...views.values()].find((x) => x.sandbox && x.sandbox.frame.contentWindow === e.source) : null;
  if (v && v.sandbox && v.sandbox.last) postSandbox(v, v.sandbox.last);
});

// A tap in a scene: on a term (<dfn title="meaning">) its meaning shows, and the voice goes on; on a part, its popup
// offers Ask about this (the question starts in the call page's text field) and Play from here.
function tapScene(v, e) {
  if (e.target.closest("a[href]")) return;
  const dfn = e.target.closest("dfn[title]");
  if (dfn) { showTerm(dfn.textContent, dfn.title, dfn); return; }
  const part = e.target.closest("[data-part]:not(.k-hidden)");
  if (!part) { closePop(); return; }
  const id = part.dataset.part, name = (v.body.source.parts || []).find((p) => p.id === id)?.name || id;
  const acts = [button(wd("ask.about"), () => { closePop(); post({ type: "stage:ask", text: `About "${name}": ` }); }, "pri")];
  if (playKey(v, "part:" + id, true)) acts.push(button(wd("play.here"), () => { closePop(); playKey(v, "part:" + id); }));
  openPop(name.charAt(0).toUpperCase() + name.slice(1), null, acts, part);
}
function showTerm(term, means, anchor) { openPop(term.trim(), means, [], anchor); }
// The popup sits under what was tapped, or over it near the stage's foot, inside a 16px gutter.
function openPop(title, text, acts, anchor) {
  spopEl.replaceChildren();
  const x = document.createElement("button"); x.type = "button"; x.className = "spop-x"; x.title = wd("close"); x.setAttribute("aria-label", wd("close"));
  x.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>`;
  x.onclick = () => closePop();
  const h = document.createElement("h3"); h.textContent = title;
  spopEl.append(x, h);
  if (text) { const p = document.createElement("p"); p.textContent = text; spopEl.append(p); }
  if (acts.length) { const row = document.createElement("div"); row.className = "sacts"; row.append(...acts); spopEl.append(row); }
  spopEl.setAttribute("aria-label", title);
  spopEl.hidden = false;
  const stage = root.querySelector(".stage").getBoundingClientRect(), r = anchor.getBoundingClientRect();
  const w = spopEl.offsetWidth, ht = spopEl.offsetHeight, below = r.bottom + 8 + ht <= stage.bottom - 8;
  spopEl.style.top = (below ? r.bottom - stage.top + 8 : Math.max(8, r.top - stage.top - ht - 8)) + "px";
  spopEl.style.left = Math.max(16, Math.min(r.left - stage.left, stage.width - w - 16)) + "px";
}
function closePop() { spopEl.hidden = true; }
// Every popup the stage holds: this one, and the step popup of each lanes board. They belong to what was on the board
// when they opened, so a board change, a new answer or a frame for another step takes them down.
function closePops() {
  closePop();
  for (const v of views.values()) for (const box of v.pane.querySelectorAll(".visual.lanes")) closeLanesPop(box);
}
document.addEventListener("pointerdown", (e) => { if (!spopEl.hidden && !spopEl.contains(e.target) && !e.target.closest?.(".scene, .vzmap, .caption, .md.grid")) closePop(); }, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !spopEl.hidden) closePop(); });

function sourceFrame(text) {
  const pre = document.createElement("pre"); pre.className = "srcframe"; pre.textContent = text;
  return pre;
}

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

// ---- Panes ---------------------------------------------------------------------------------

// `update`: an in-place change to the view being read, so what changed may pulse.
function fillPane(v, update = false) {
  const { source: src, rev, title } = v.body;
  const seq = v.renderSeq = (v.renderSeq || 0) + 1;
  const first = !v.filled;
  v.prev = update ? { ...v.snap } : null;
  v.filled = true; v.stale = false; v.applied = null;
  const body = document.createElement("div"); body.className = "pbody";
  v.pane.replaceChildren(header(v), body);
  if (langOf(src)) v.pane.setAttribute("lang", "el"); else v.pane.removeAttribute("lang");
  if (src.type === "inline") {
    const box = renderInline(v, seq);
    body.append(box);
    if (src.format === "code" && first) requestAnimationFrame(() => scrollToMark(box));
    const left = src.format === "change" && src.hunks_total ? src.hunks_total - src.hunks.length : 0;
    if (src.format === "change" && (src.more > 0 || (left > 0 && src.hunks.length && src.hunks[0].n))) {
      const more = document.createElement("p"); more.className = "more";
      const picked = src.hunks.length && src.hunks_total && !src.more ? `hunks ${src.hunks.map((h) => h.n).join(", ")} of ${src.hunks_total} shown` : "";
      more.textContent = picked || `${src.more} more changed ${src.more === 1 ? "line" : "lines"} not shown` + (left > 0 ? `, in ${left} more ${left === 1 ? "hunk" : "hunks"}` : "");
      body.append(more);
    }
    return;
  }
  v.prev = null;
  if (src.type === "file" && src.missing) {
    const p = document.createElement("p"); p.className = "waiting";
    p.textContent = wd("file.wait", { path: src.path }); body.append(p); return;
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
    .catch((err) => { if (current()) note(box, wd("file.fail", { path: src.path, why: err.message }), () => fillPane(v)); });
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

// The Key points board is the one the call names itself, in English; the stage says its name in the page's language.
const shownTitle = (v) => (v.body.source?.type === "inline" && v.body.source.format === "points" ? wd("points.title") : v.body.title);
function setTabTitle(v) {
  v.tab.querySelector(".ttl").textContent = shownTitle(v);
  v.tab.title = shownTitle(v);
  v.tab.querySelector(".ico")?.remove();
  v.tab.insertAdjacentHTML("afterbegin", icon(kindOf(v.body.source)));
  v.tab.querySelector(".count")?.remove();
  const src = v.body.source;
  if (src.type === "inline" && src.format === "points") {
    const c = document.createElement("span"); c.className = "count";
    c.textContent = src.items.length; c.title = wdn("points.count", src.items.length);
    v.tab.append(c);
  }
  markUpdated(v, v.tab.classList.contains("updated"));
}
function markUpdated(v, on) {
  v.tab.classList.toggle("updated", on);
  if (on) v.tab.setAttribute("aria-label", wd("updated.aria", { title: shownTitle(v) })); else v.tab.removeAttribute("aria-label");
  updateNav();
}

// The boards are one stage with a history: ‹ and › walk it, "Board 2 of 5" opens the list of every board, in the order it counts them, and its dot says a board changed while another was in front. The tabs are the list's rows.
function updateNav() {
  const tabs = [...tabsEl.children], i = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
  navEl.hidden = tabs.length < 2;
  if (navEl.hidden) showBoards(false);
  navEl.querySelector(".tabpos").textContent = i >= 0 ? wd("board.pos", { i: i + 1, n: tabs.length }) : wd("board.count", { n: tabs.length });
  navEl.querySelector(".prev").disabled = i <= 0;
  navEl.querySelector(".next").disabled = i < 0 || i >= tabs.length - 1;
  const changed = tabs.some((t) => t.classList.contains("updated") && t.getAttribute("aria-selected") !== "true");
  navEl.querySelector(".posdot").hidden = !changed;
  // The name starts with the visible words, so a voice command or a screen reader finds the control by what it shows.
  posEl.setAttribute("aria-label", wd("board.all.aria", { pos: navEl.querySelector(".tabpos").textContent }) + (changed ? wd("board.changed") : ""));
}
// The pane headers start after the history buttons and Back to the voice, which sit over their left end.
const barRoom = () => root.querySelector(".stage").style.setProperty("--navw",
  (navEl.hidden ? 0 : navEl.offsetWidth) + (followEl.hidden ? 0 : followEl.offsetWidth + 14) + "px");  // its 6px margin, and 8px before the title
const barObserver = new ResizeObserver(barRoom);
barObserver.observe(navEl); barObserver.observe(followEl);
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
// On a stage opened on its own, ← and → walk the boards, as the ‹ and › buttons do.
if (!embedded) document.addEventListener("keydown", (e) => {
  if (!["ArrowLeft", "ArrowRight"].includes(e.key) || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
  const at = document.activeElement;
  if (at && at.closest("input, textarea, select, [contenteditable], .boards")) return;
  const btn = root.querySelector(e.key === "ArrowLeft" ? ".navbtn.prev" : ".navbtn.next");
  if (!btn || btn.disabled) return;
  e.preventDefault();
  btn.click();
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
  updateNav();  // once every tab is marked: mid-loop, the board left behind still counts as selected
  if (was !== name) closePops();
  if (was !== name) post({ type: "stage:shown", view: name });  // the call's Play plays the board in front
  if (captionText) placeCaption();
}

// A pinned view (Key points) leads the history, whatever the layout's order. The list shows the boards in this order, top to bottom,
// the same order "Board i of n" counts in.
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
  // a scene saved before frames named what is said gets the arrow rule of today's scenes (scene.js settled)
  if (body.scene) body.scene = settled(body.scene);
  for (const n of Object.keys(body.scenes || {})) body.scenes[n] = settled(body.scenes[n]);
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
  if (!same(was, sceneOf(v))) startFrame(v);
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
  v.renderSeq++;  // drop any fill still waiting for it
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

// Following lives on the call page's gear; the stage keeps the state and tells the page when it
// changes here.
// While it is off, Back to the voice shows beside the history: the board the reader picked stays in front,
// whatever they play, until they press it or the next answer starts.
function setFollow(on) {
  if (follow === on) return;
  follow = on;
  followEl.hidden = !embedded || on;
  barRoom();
  post({ type: "stage:follow", on });
}
followEl.onclick = () => { setFollow(true); frontVoice(); };
// After a click with the pointer (not Enter or Space on the button, which have no click position: detail 0), a step,
// board or follow button hands focus back to the page, so Space plays or pauses the answer instead of pressing it again.
document.addEventListener("click", (e) => {
  if (e.detail > 0) e.target.closest?.(".stepbar .btn, .vstep, .navbtn, button[role=tab], .follow")?.blur();
});

// Centre `el` (an element, or several taken together, such as the lines of a range) in each box around it
// that scrolls, inside the pane only: never the page around the stage. What is taller than the box starts at
// its top instead. `room`: the foot of the board kept clear, which the element is centred above.
function centre(el, room = 0, keepOnly = false) {
  const els = (Array.isArray(el) ? el : [el]).filter((e) => e && e.isConnected && e.getClientRects().length);  // not one drawn nowhere (the other orientation of a graph)
  if (!els.length) return;
  const behavior = reduced() ? "auto" : "smooth";
  for (let box = els[0].parentElement; box && box !== panesEl; box = box.parentElement) {
    if (box.scrollHeight <= box.clientHeight + 1 || !/auto|scroll/.test(getComputedStyle(box).overflowY)) continue;
    const rs = els.map((e) => e.getBoundingClientRect()), b = box.getBoundingClientRect();
    const lead = box.querySelector(".slide .title");   // a slide's title is not left cut at the pane's edge
    const at = { top: Math.min(...rs.map((r) => r.top)), bottom: Math.max(...rs.map((r) => r.bottom)), box: b, view: b.height - room, scroll: box.scrollTop };
    box.scrollTo({ top: keepOnly ? keepTarget(at) : centreTarget({ ...at, lead: lead ? lead.getBoundingClientRect().bottom - b.top + box.scrollTop : 0 }), behavior });
  }
}

// Every box around `el` that scrolls, inside the pane only, back to its top.
function toTop(el) {
  const behavior = reduced() ? "auto" : "smooth";
  for (let box = el; box && box !== panesEl; box = box.parentElement) {
    if (box.scrollTop > 0 && /auto|scroll/.test(getComputedStyle(box).overflowY)) box.scrollTo({ top: 0, behavior });
  }
}

// The board the voice fronted before it reached the stage, {name, answer}: fronted when it arrives.
let lateFront = null;
// The board the voice fronted last, whether or not the stage followed it at the time. When following comes back (Back to the
// voice, the gear, a new answer with no board of its own) the stage returns to it: a board the reader picked by hand, Key
// points among them, does not keep the stage once the voice is followed again.
let voiceFront = null;
function frontVoice() {
  const v = voiceFront && views.get(voiceFront);
  if (!v || v.body.pinned || selectedName() === voiceFront) return false;
  select(voiceFront, true);
  return true;
}
function front(name, manual, answer = null) {
  if (!manual && name) voiceFront = name;
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

// The grid of a table board in frame n: the rows being said (`g-cur`), the columns (`g-col`), and the cells pointed at
// (`k-focus`, set with the frame's keys). A pair of cells lights those two and not the rows round them. Returns what to
// keep in view: the lit rows, cells, or for a column its header.
function paintGrid(box, scene, n) {
  const said = beingSaid(scene, n), frame = scene.frames[Math.max(0, Math.min(n, scene.frames.length - 1))];
  const cells = new Set((frame.focus || []).filter((k) => k.startsWith("cell#")));
  const tables = [...box.querySelectorAll("table")], many = tables.length > 1;
  const colKey = (table, c) => (many ? `col#${table.dataset.t}.${c}` : `col#${c}`);
  const cellRows = new Set([...cells].map((k) => "row#" + k.slice(5).split(".")[0]));
  const colsLit = new Set(said.filter((k) => k.startsWith("col#")));
  // every cell of a column pointed at one by one is that column, lit as one
  for (const table of tables) {
    const body = [...table.querySelectorAll("tbody tr")];
    for (let c = 1; body.length > 1 && c <= (body[0]?.children.length || 0); c++) {
      const own = body.map((tr) => tr.children[c - 1]?.dataset.key);
      if (own.every((k) => k && cells.has(k))) { colsLit.add(colKey(table, c)); own.forEach((k) => cells.delete(k)); }
    }
  }
  const rowsLit = new Set(said.filter((k) => k.startsWith("row#") && !(cellRows.has(k) && !frame.focus.includes(k))));
  for (const tr of box.querySelectorAll("tbody tr")) tr.classList.toggle("g-cur", rowsLit.has(tr.dataset.key));
  const litCols = [];
  for (const table of tables) {
    for (const el of table.querySelectorAll("[data-c]")) {
      const on = colsLit.has(colKey(table, el.dataset.c));
      el.classList.toggle("g-col", on);
      if (on && el.tagName === "TH") litCols.push(el);
    }
  }
  box.classList.toggle("g-on", rowsLit.size + colsLit.size + cells.size > 0);
  const rest = n >= scene.rest;   // only the whole board is drawn larger on a wide screen: a step moves nothing
  if (box.classList.contains("g-rest") !== rest) { box.classList.toggle("g-rest", rest); refit(box); }
  const keep = [...box.querySelectorAll("tbody tr.g-cur"), ...box.querySelectorAll("td.k-focus:not(.g-col)"), ...litCols];
  return keep;
}

// Layout has settled when the pane is shown and its boxes have stopped changing size: a board fronted this moment is
// still hidden or growing, and one scroll right then lands on the wrong place. So the view is brought to what is lit
// once a frame later, again as the box resizes (when the browser can say so) and once more when the animations are done.
function settleThen(v, box, n, run) {
  const go = () => { if (box.isConnected && !v.pane.hidden && v.applied === n) run(); };
  requestAnimationFrame(() => requestAnimationFrame(go));
  setTimeout(go, 450);
  if (typeof ResizeObserver === "function") {
    let quiet = 0;
    const ro = new ResizeObserver(() => { clearTimeout(quiet); quiet = setTimeout(go, 80); });
    ro.observe(box); const wrap = box.querySelector(".tablewrap"); if (wrap) ro.observe(wrap);
    setTimeout(() => ro.disconnect(), 1500);
  }
}

// Scroll the table's own box (rows under its sticky header, columns beside the sticky first one) and the boxes round
// it so every lit element is in view: centred when they fit, else their top and left edge first.
function bringInView(box, els) {
  const lit = els.filter((e) => e && e.isConnected);
  if (!lit.length) return;
  const wrap = lit[0].closest(".tablewrap");
  if (wrap) {
    scrollCue(wrap);
    const b = wrap.getBoundingClientRect(), rs = lit.map((e) => e.getBoundingClientRect());
    const head = wrap.querySelector("thead")?.getBoundingClientRect().height || 0;
    const key = wrap.classList.contains("sticky-key") ? (wrap.querySelector("td.key")?.getBoundingClientRect().width || 0) : 0;
    const top = Math.min(...rs.map((r) => r.top)), bottom = Math.max(...rs.map((r) => r.bottom));
    const left = Math.min(...rs.map((r) => r.left)), right = Math.max(...rs.map((r) => r.right));
    const behavior = reduced() ? "auto" : "smooth";
    const y = bottom - top <= b.height - head ? (top + bottom) / 2 - (b.top + head + (b.height - head) / 2) : top - b.top - head - 8;
    const lone = lit.every((e) => e.tagName === "TD" || e.tagName === "TH") && !lit.some((e) => e.matches(".key"));
    const x = lone && wrap.scrollWidth > wrap.clientWidth + 1
      ? (right - left <= b.width - key ? (left + right) / 2 - (b.left + key + (b.width - key) / 2) : left - b.left - key - 8) : 0;
    if (Math.abs(y) > 1 || Math.abs(x) > 1) wrap.scrollTo({ top: wrap.scrollTop + y, left: wrap.scrollLeft + x, behavior });
  }
  if (!wrap || wrap.scrollHeight <= wrap.clientHeight + 1) centre(lit);  // a table that scrolls itself is placed above
}

function paintFrame(v, box, animate = false) {
  const on = painted(v);
  box = box || v.pane.querySelector(".code, .md, .visual");
  if (!on && box && box.classList.contains("sandboxed")) {  // no answer steps it: the whole scene shows
    const all = (v.body.source.parts || []).map((p) => "part:" + p.id);
    postSandbox(v, { show: all, focus: [], cur: [], animate: false });
  }
  if (!on || !box) return;
  const { scene, n } = on;
  if (v.applied !== n && selectedName() === v.body.name) closePop();   // a frame for another step: its popup is of the one before
  if (box.classList.contains("sandboxed")) {
    const last = scene.frames.length - 1, frame = scene.frames[Math.max(0, Math.min(n, last))];
    postSandbox(v, { show: frame.show, focus: frame.focus, cur: beingSaid(scene, n), animate });
    v.applied = n;
    stepText(v, scene, n);
    return;
  }
  // a scene's nested parts rise in on a forward step only, so the class is set before the frame shows them
  if (box.classList.contains("scene")) box.classList.toggle("s-play", !!(animate && v.applied === n - 1));
  const done = applyFrame(scene, box, n, animate && v.applied === n - 1 ? v.applied : null);
  if (!done) return;
  if (box.classList.contains("lanes")) { layoutLanes(box, scene, n); done.focused = null; }  // lanes scroll themselves
  // the map is placed to fit; on one taller than its board, the card being said is kept in view
  if (box.classList.contains("map")) done.focused = layoutMap(box, scene, n, animate && v.applied === n - 1);
  if (box.classList.contains("vzmap")) {
    const said = layoutVzMap(box, scene, n), lit = withEnds(box.querySelector("svg.vz") || box, done.focused.length ? done.focused : said);
    done.focused = lit;
    requestAnimationFrame(() => { if (!v.pane.hidden) centreAcross(box, lit); });  // a map wider than its board
  }
  if (box.classList.contains("scene")) {
    // the part being said is marked, and kept in view with what is pointed at
    const cur = new Set(beingSaid(scene, n));
    const said = [...box.querySelectorAll("[data-key]")].filter((el) => { const on = cur.has(el.dataset.key); el.classList.toggle("s-cur", on); return on; });
    box.classList.toggle("s-on", said.length > 0);  // the parts shown before the one being said step back
    if (!done.focused.length) done.focused = said;
  }
  if (box.classList.contains("screenb")) {
    paintScreen(box, scene, n, beingSaid);  // the screen of the part being said, lit, with its text beside it
    done.focused = [];  // the board fits its pane: nothing to scroll into view
  }
  if (box.classList.contains("grid")) done.focused = paintGrid(box, scene, n);
  v.applied = n;
  markCurrent(box, new Set(beingSaid(scene, n)));
  // Checked a frame later: a pane filled as it is fronted is still hidden while it paints.
  const room = box.classList.contains("map") ? +box.dataset.room || 0 : 0;
  const keep = [done.focused].flat().filter(Boolean);
  if (keep.length && box.classList.contains("grid")) settleThen(v, box, n, () => bringInView(box, keep));
  else if (keep.length) requestAnimationFrame(() => { if (!v.pane.hidden) centre(keep, room, box.classList.contains("vzbars")); });  // bars start at their title
  else if (box.classList.contains("scene") && n >= scene.rest) requestAnimationFrame(() => { if (!v.pane.hidden) toTop(box); });  // at rest a slide shows from its title
  else if (box.classList.contains("vzbars") && n >= scene.rest) requestAnimationFrame(() => { if (!v.pane.hidden) toTop(box); });  // at rest bars show from their title
  if (captionText) requestAnimationFrame(() => placeCaption());
  stepText(v, scene, n);
  const back = v.pane.querySelector(".stepback"), next = v.pane.querySelector(".stepnext");
  if (back) back.disabled = n <= 0;
  if (next) next.disabled = n >= scene.rest;
}

// The part being said is exposed as the current one (aria-current), so a screen reader can find it; nothing is drawn for it.
function markCurrent(box, said) {
  for (const el of box.querySelectorAll("[data-key]")) {
    if (said.has(el.dataset.key)) el.setAttribute("aria-current", "true"); else el.removeAttribute("aria-current");
  }
}
// "Read the board as text" on the call page: the board's outline, said back to the page.
function postOutline(name) {
  const v = views.get(name), box = v?.pane?.querySelector(".code, .md, .visual");
  post({ type: "stage:outline", view: name, title: v ? shownTitle(v) : "", ...outlineOf(box) });
}

// The step button's words, and what pressing it does: step on, or from the rest frame start again.
function stepText(v, scene, n) {
  const step = v.pane.querySelector(".vstep");
  if (!step) return;
  step.textContent = stepLabel(scene, n);
  const label = n >= scene.rest ? wd("step.all.again") : wd("step.then.next", { label: stepLabel(scene, n) });
  step.title = label; step.setAttribute("aria-label", label);
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

// An answer that has ended leaves each board it stepped whole: one a later answer has taken, or the one in
// front that the reader took in hand, stays as it is.
function restAfter(names, answer) {
  for (const name of names) {
    const v = views.get(String(name));
    if (!v || (!follow && selectedName() === v.body.name)) continue;
    if (v.body.scenes && answerKey(answer) !== null && v.answer !== answerKey(answer)) continue;
    toRest(v);
  }
}

// An answer with no board of its own leaves the board in front where it is, and that board is shown whole: never
// stopped half way through the steps of an earlier answer (faint rows under "Following", a voice that is not on it).
// The board the reader took in hand stays as it is.
function restUnstepped() {
  for (const v of views.values()) {
    if (!follow && selectedName() === v.body.name) continue;
    toRest(v);
  }
}

// The stage's own words again, in the language just set: the toolbar and its lists, the empty card, every board's header,
// and the boards whose drawing holds words (a diagram's lanes, the key points).
function relabel() {
  document.documentElement.lang = getLang();
  root.querySelector(".tabbar").setAttribute("lang", getLang());
  followEl.textContent = wd("back.voice"); followEl.title = wd("back.voice"); followEl.setAttribute("aria-label", wd("back.voice"));
  navEl.setAttribute("aria-label", wd("boards"));
  navEl.querySelector(".prev").setAttribute("aria-label", wd("board.prev"));
  navEl.querySelector(".next").setAttribute("aria-label", wd("board.next"));
  boardsEl.querySelector("h4").textContent = wd("boards");
  tabsEl.setAttribute("aria-label", wd("stage.label"));
  stopEl.setAttribute("aria-label", wd("stop.group"));
  const card = panesEl.querySelector(".emptycard");
  if (card && !panesEl.querySelector(".empty").classList.contains("failed")) {
    card.querySelector("h2").textContent = wd("empty.title"); card.querySelector(".msg").textContent = wd("empty.line");
  }
  const tiles = card ? [...card.querySelectorAll(".tile > span")] : [];
  ["code", "diagram", "table", "page"].forEach((k, i) => { if (tiles[i]) tiles[i].textContent = wd("kind." + k); });
  card?.querySelector(".retry")?.replaceChildren(wd("retry"));
  for (const v of views.values()) {
    setTabTitle(v);
    if (!v.filled) continue;
    const src = v.body.source;
    if (src.type === "inline" && (src.format === "visual" || src.format === "points")) {
      if (v.pane.hidden) v.stale = true; else fillPane(v, true);
      continue;
    }
    const old = v.pane.querySelector("header.phead");
    if (old) old.replaceWith(header(v));
    const sc = hasScene(v) ? sceneOf(v) || painted(v)?.scene : null;
    if (sc && v.applied != null) {
      stepText(v, sc, v.applied);
      const back = v.pane.querySelector(".stepback"), next = v.pane.querySelector(".stepnext");
      if (back) back.disabled = v.applied <= 0;
      if (next) next.disabled = v.applied >= sc.rest;
    }
  }
  updateNav(); barRoom();
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
    closePops();
    if (m.follow !== false) setFollow(true);
    for (const [name, late] of lateFrames) if (late.answer !== answerKey(m.n)) lateFrames.delete(name);
    if (lateFront && lateFront.answer !== answerKey(m.n)) lateFront = null;
  }
  else if (m.type === "stage:rest") restAfter(Array.isArray(m.views) ? m.views : [], m.answer);
  else if (m.type === "stage:zoom") {
    const z = Number(m.zoom);
    if (z >= 0.5 && z <= 3) {
      document.documentElement.style.zoom = z === 1 ? "" : String(z);
      document.documentElement.style.setProperty("--z", String(z));   // the stylesheet's vh and vw units are of the window, not of the zoomed page
      for (const box of document.querySelectorAll(".md.grid")) refit(box);   // a table at rest is drawn larger by the room it has, less the zoom
    }
  }
  else if (m.type === "stage:theme") {
    const theme = m.theme === "dark" ? "dark" : "light";
    if (document.documentElement.dataset.theme === theme) return;
    document.documentElement.dataset.theme = theme;
    for (const f of document.querySelectorAll("iframe.frame")) themeFrame(f);
    for (const v of views.values()) if (v.sandbox && v.sandbox.last) postSandbox(v, v.sandbox.last);
  }
  else if (m.type === "stage:lang") { if (setLang(m.lang)) relabel(); }
  else if (m.type === "stage:follow") { setFollow(!!m.on); if (m.on && m.front) frontVoice(); }
  else if (m.type === "stage:outline") postOutline(String(m.view || ""));
  else if (m.type === "stage:caption") { captionText = String(m.text || ""); placeCaption(); }
  else if (m.type === "stage:stop") paintStop(m.stop && typeof m.stop === "object" ? m : null);
  else if (m.type === "stage:frame") setFrame(String(m.view), Number(m.n), !!m.animate, m.answer);
  else if (m.type === "stage:state") {
    lateFrames.clear(); lateFront = null;  // the whole picture: a late frame or front it still wants is in it again
    for (const [name, n] of Object.entries(m.frames || {})) {
      try { setFrame(name, Number(n), false, m.answer); } catch (e) { console.error("stage:", e); }  // one board never stops the rest
    }
    if (m.front) front(String(m.front), false, m.answer);
    else if (!Object.keys(m.frames || {}).length) {   // an answer with no board of its own
      restUnstepped();
      if (follow && views.get(selectedName())?.body.pinned) frontVoice();   // Key points was fronted by hand: back to the board the voice showed
    }
    lightKey(Number(m.keys) || 0, false);
  }
}

// A stop: the answer asks and waits, on a card at the foot of the stage, in place of the caption. A press goes
// to the call page, which plays on, plays again, or sends a turn; a guess shows right and wrong once picked.
function paintStop(m) {
  stopEl.hidden = !m;
  stopEl.replaceChildren();
  if (m) {
    const { stop } = m, picked = Number.isInteger(stop.picked) ? stop.picked : null;
    stopEl.dataset.type = stop.type;
    const q = document.createElement("p"); q.className = "sq"; q.textContent = stop.question || "Want more?";
    const row = document.createElement("div"); row.className = "sbtns";
    (stop.choices || []).forEach((label, k) => {
      const b = button(String(label), () => post({ type: "stage:pick", answer: m.answer, i: m.i, choice: k }));
      if (picked !== null) {
        b.disabled = true;
        if (stop.right === k) b.classList.add("right");
        else if (picked === k) b.classList.add("wrong");
      }
      row.append(b);
    });
    if (stop.type === "sayback") { const h = document.createElement("p"); h.className = "shint"; h.textContent = wd("say.hint"); row.append(h); }
    stopEl.append(q, row);
  }
  placeCaption();
}

// The caption's words, with each term the scene in front defines (<dfn title>) as a button that shows its meaning.
function captionWords(v) {
  const terms = new Map();
  for (const d of (v && !v.pane.hidden ? v.pane.querySelectorAll(".scene dfn[title]") : [])) {
    const t = d.textContent.trim();
    if (t && !terms.has(t.toLowerCase())) terms.set(t.toLowerCase(), [t, d.title]);
  }
  captionEl.replaceChildren();
  if (!terms.size) { captionEl.textContent = captionText; return; }
  const alts = [...terms.keys()].sort((a, b) => b.length - a.length).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(?<![\\p{L}\\p{N}])(${alts.join("|")})(?![\\p{L}\\p{N}])`, "giu");
  let at = 0;
  for (const m of captionText.matchAll(re)) {
    captionEl.append(captionText.slice(at, m.index));
    const [, means] = terms.get(m[0].toLowerCase());
    const b = document.createElement("button"); b.type = "button"; b.className = "term"; b.textContent = m[0];
    b.onclick = () => showTerm(m[0], means, b);
    captionEl.append(b);
    at = m.index + m[0].length;
  }
  captionEl.append(captionText.slice(at));
}

// The sentence being said: under the part being said when the board in front is a scene, else at the foot.
let captionText = "";
// Placing it scrolls the scene up just enough for the bubble to fit under the part (the scene keeps room
// at its foot for that), so it never covers a part already shown. It goes above only when the part
// itself fills the stage. A scroll moves it along (`scrolled`) without scrolling again.
function placeCaption(scrolled = false) {
  captionEl.hidden = !captionText || !stopEl.hidden;
  root.querySelector(".stage").classList.toggle("has-cap", !captionEl.hidden);  // a phone keeps room for it at the board's foot
  const name = selectedName(), v = name && views.get(name);
  if (!scrolled) captionWords(v);
  // a slide keeps the sentence in a bar across its foot; an older scene puts it in a bubble under the part
  const slide = v && !v.pane.hidden && v.pane.querySelector(".visual.scene > .slide");
  const part = !slide && v && !v.pane.hidden && [...v.pane.querySelectorAll(".scene .k-focus, .scene .s-cur")].pop();
  captionEl.className = "caption" + (!captionText ? "" : part ? " bubble" : " bar") + (slide && captionText ? " sub" : "");
  captionEl.style.left = captionEl.style.top = "";
  if (!captionText || !part || !stopEl.hidden) return;
  const stage = root.querySelector(".stage").getBoundingClientRect();
  const h = captionEl.offsetHeight, w = captionEl.offsetWidth;
  let r = part.getBoundingClientRect();
  const short = r.bottom + 10 + h - (stage.bottom - 8), box = part.closest(".visual.scene");
  if (!scrolled && short > 0 && box && r.top - short >= box.getBoundingClientRect().top) {
    box.scrollTop += short;
    r = part.getBoundingClientRect();
  }
  const below = r.bottom + 10 + h <= stage.bottom - 8;
  captionEl.style.top = (below ? r.bottom - stage.top + 10 : Math.max(8, r.top - stage.top - h - 10)) + "px";
  captionEl.style.left = Math.max(16, Math.min(r.left - stage.left, stage.width - w - 16)) + "px";
  captionEl.classList.toggle("above", !below);
}
window.addEventListener("resize", () => placeCaption());
document.addEventListener("scroll", (e) => { if (captionText && e.target.closest?.(".visual.scene")) placeCaption(true); }, true);

function post(msg) { if (embedded) window.parent.postMessage(msg, "*"); }
// Play from here, on a sequence step: the first frame that says the step, in the scene on the board, else in
// the latest answer's scene that says it. False when no answer says it; `dry` only asks.
function playStep(v, step, dry = false) { return playKey(v, "step:" + step, dry); }
// The same for any key a scene's frames say: a scene part ("part:<id>") as much as a sequence step.
function playKey(v, key, dry = false) {
  const scenes = v.body.scenes || {};
  const own = v.answer != null ? [[String(v.answer), scenes[v.answer]]] : [];
  const tries = [...own, ...Object.entries(scenes).sort((a, b) => Number(b[0]) - Number(a[0]))];
  if (v.body.scene && v.body.answer != null) tries.push([String(v.body.answer), v.body.scene]);
  for (const [answer, scene] of tries) {
    if (!scene) continue;
    for (let n = 1; n < scene.frames.length && n < scene.rest; n++) {
      if (beingSaid(scene, n).includes(key)) { if (!dry) post({ type: "stage:play", view: v.body.name, answer: Number(answer), n }); return true; }
    }
  }
  return false;
}
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
    card.querySelector("h2").textContent = wd("fail.title");
    card.querySelector(".msg").textContent = wd("fail.line", { why: e?.message || e });
    if (!card.querySelector(".retry")) card.append(button(wd("retry"), loadSnapshot, "retry"));
    postReady();  // the stage has painted, with its own message and button
    return;
  }
  panel.classList.remove("failed");
  card.querySelector("h2").textContent = wd("empty.title");
  card.querySelector(".msg").textContent = wd("empty.line");
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

window.__stageTest = { splitLines, highlightLines, onMessage, markRange, pairEdits,
  frames: () => Object.fromEntries([...views].map(([name, v]) => [name, v.applied])) };
await loadSnapshot();
