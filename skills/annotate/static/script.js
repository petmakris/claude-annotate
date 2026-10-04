// annotate skill — client-side incremental rendering and per-block submission
//
// The page code is one program in nine files, split along its own section
// markers: script.js (this: drafts, block rendering, choice, mockup),
// script-settings.js, script-explain.js, script-blocks.js, script-cards.js,
// script-chrome.js, script-poll.js, script-changes.js, script-reconcile.js.
// entry.js loads them in that order. They were one IIFE and are now plain
// classic scripts, so what each declares at the top level is visible to the
// others (and to the page) the way the IIFE's locals were visible to all of
// it; skills/annotate/tests/test_script_parts.py keeps those names from
// colliding with anything else on the page. A part runs top to bottom when it
// loads, so a call made at load time can only reach what an earlier part (or
// its own) declared — the boot itself lives at the end of the last part.

// Base path of the page, e.g. "/" or "/s/<sid>/". Relative fetches use this.
const BASE = (() => {
  const p = window.location.pathname;
  return p.endsWith("/") ? p : p + "/";
})();

// The slug (or sid) this page is served under — "/s/<key>/" — which the server
// resolves either way. Empty on the index, which renders no code panes.
// A hue from a name, stable forever. djb2 over the code units, folded to a
// degree — no randomness and no counter, so "benzene" is the same colour in
// every pane of every page, which is the only property that makes the tint
// worth having. Saturation and lightness stay with the theme (see .cp-proj
// in style.css); only the hue travels, so a dark theme is not handed a pale
// pill it cannot paint text on.
// A curated wheel rather than `hash % 360`, and the reason is a real result:
// taking the hash straight to a degree put `app-worktrees` on hue 14
// and the skills repository (under its old name) on hue 15. One degree apart reads as a
// rendering fault, not as two projects — the worst outcome, because it is
// neither "the same" nor "different". Landing on a fixed set of separated
// hues means two projects are either plainly distinct or exactly equal, and
// an honest collision is easier to live with than a near-miss.
const PILL_HUES = [210, 145, 25, 275, 190, 45, 330, 95, 250, 5, 165, 300, 65, 230];
const hueFromName = (name) => {
  let h = 5381;
  for (let i = 0; i < name.length; i++) h = ((h * 33) ^ name.charCodeAt(i)) >>> 0;
  return PILL_HUES[h % PILL_HUES.length];
};

// Inline SVG rather than a glyph font or an emoji: the header is 11px and
// needs to line up with text, and an icon that inherits `currentColor`
// recolours itself with the theme instead of needing one rule per theme.
const icon = (paths, label) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "13");
  svg.setAttribute("height", "13");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.6");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  paths.forEach(d => {
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  });
  if (label) svg.setAttribute("data-icon", label);
  return svg;
};
const ICON_OPEN   = ["M13.5 8.5v4a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h4",
                     "M9.5 2.5h4v4", "M7 9l6.5-6.5"];

const workspaceKey = () => {
  const m = BASE.match(/^\/s\/([^/]+)\//);
  return m ? decodeURIComponent(m[1]) : "";
};

const proseEl = document.querySelector("main.prose");
// `let`: a new response in the same session moves the drafts to a new key.
let STORAGE_KEY = `annotate.drafts.${document.body.dataset.responseId || ""}`;

// Pending rounds, drafts and unsent general comments are kept per response
// or per session, and every response ever opened used to leave its keys
// behind for good. Each write stamps its key here; a key not written for
// STALE_AFTER_MS is removed on the next load of any annotate page. Keys from
// before the stamps existed are stamped the first time they are seen, so
// they are retired on the same clock rather than all at once today.
window.AnnotateStorage = (() => {
  const INDEX = "annotate.touched";
  const STALE_AFTER_MS = 30 * 24 * 3600 * 1000;
  const SWEPT = /^annotate\.(round|drafts|general|inflight)\./;
  // Collapse, per-response view and highlighter state. Written on every
  // click and never stamped, so these age by the last time their RESPONSE
  // was opened, kept in OPENED. Global settings (`annotate.view:<name>`,
  // one colon) do not match and are never swept.
  const PER_RESPONSE =
    /^annotate\.(view|read|collapsed|flavour|flowview):([^:]+):/;
  // Keys nothing reads any more, removed on sight: the old diagram-choice
  // keys (one per block id, shared by every document); the per-pane widen
  // state and the code-pane layout, from when a pane could sit beside the
  // prose; the prose font, from when there was more than one; and the
  // pre-rename page width, whose every value is narrower than Normal now.
  const RETIRED = new RegExp([
    "^annotate\\.(flavour|view)\\.[^:]+$",
    "^annotate\\.codewide:",
    "^annotate\\.view:prosefont$",
    "^annotate\\.view:[^:]+:codelayout$",
    "^annotate\\.view:[^:]+:width$",
  ].join("|"));
  const OPENED = "annotate.opened";
  const read = () => {
    try { return JSON.parse(localStorage.getItem(INDEX) || "{}") || {}; }
    catch (_) { return {}; }
  };
  const write = (idx) => {
    try { localStorage.setItem(INDEX, JSON.stringify(idx)); } catch (_) {}
  };
  function touch(key) {
    const idx = read();
    idx[key] = Date.now();
    write(idx);
  }
  function sweep() {
    const idx = read();
    const now = Date.now();
    let keys = [];
    try { keys = Object.keys(localStorage); } catch (_) { return; }
    for (const key of keys) {
      if (!SWEPT.test(key)) continue;
      if (!(key in idx)) { idx[key] = now; continue; }
      if (now - idx[key] > STALE_AFTER_MS) {
        try { localStorage.removeItem(key); } catch (_) {}
        delete idx[key];
      }
    }
    for (const key of Object.keys(idx)) if (!keys.includes(key)) delete idx[key];
    write(idx);

    let opened = {};
    try { opened = JSON.parse(localStorage.getItem(OPENED) || "{}") || {}; }
    catch (_) {}
    const rid = document.body.dataset.responseId;
    if (rid) opened[rid] = now;
    for (const key of keys) {
      if (RETIRED.test(key)) {
        try { localStorage.removeItem(key); } catch (_) {}
        continue;
      }
      const m = PER_RESPONSE.exec(key);
      if (!m) continue;
      // Unknown response: its keys predate this record, so start its clock.
      if (!(m[2] in opened)) { opened[m[2]] = now; continue; }
      if (now - opened[m[2]] > STALE_AFTER_MS) {
        try { localStorage.removeItem(key); } catch (_) {}
      }
    }
    for (const r of Object.keys(opened)) {
      if (now - opened[r] > STALE_AFTER_MS) delete opened[r];
    }
    try { localStorage.setItem(OPENED, JSON.stringify(opened)); } catch (_) {}
  }
  return { touch, sweep };
})();
window.AnnotateStorage.sweep();

const commentMd = (typeof window.markdownit === "function")
  ? window.markdownit({ html: false, linkify: true, typographer: false, breaks: true })
  : null;

// ── Drafts ─────────────────────────────────────────────────────────────────
// annotations: { [annotId]: { block_id, type, selected_text, comment, images? } }
let annotations = loadDrafts();

// Submitted comments awaiting Claude's ack: event_id -> { blockId } for a
// block/diagram/choice comment, or { general: true } for a page-level one.
// The block "updating" overlay / composer status line resolves when the
// matching event_id appears in /poll's consumed_events — the real done-signal,
// which does NOT depend on Claude rewriting the commented block specifically.
const pendingEvents = new Map();

// CSS.escape fallback (older engines): block/step/annotate ids can be
// Claude-authored, so a raw `[data-block-id="${id}"]` would throw on a quote.
const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s).replace(/["\\\]]/g, "\\$&");

function loadDrafts() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    // An empty draft does not survive the session that opened it. It holds
    // nothing the reader typed — `selected_text` is scope, not content — so
    // restoring one only paints an engaged bar on a block nobody is
    // commenting on. Dropped here rather than in renderComments, which
    // cannot tell a draft that was abandoned last week from the one being
    // opened right now.
    for (const [id, a] of Object.entries(stored)) {
      if (isEmptyDraft(a)) delete stored[id];
    }
    return stored;
  } catch { return {}; }
}

function saveDrafts() {
  try {
    if (Object.keys(annotations).length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(annotations));
      window.AnnotateStorage.touch(STORAGE_KEY);
    } else localStorage.removeItem(STORAGE_KEY);
  } catch {}
}

// ── Rendering ──────────────────────────────────────────────────────────────
const PLACEHOLDER_TEXT = { comment: "Your comment…" };

// A draft the user never wrote anything into. It carries no information —
// `selected_text` is scope, not content — so it must never outlive the click
// that made it: it paints the engaged bar on a block nobody is commenting on,
// and because only one draft may exist at a time it also silently blocks
// every other block from opening a comment.
function isEmptyDraft(a) {
  return a && !(a.comment || "").trim()
      && !(a.images || []).length;
}

function applyEngagedStyling() {
  document.querySelectorAll("[data-block-id][data-engaged-type]").forEach(b => {
    delete b.dataset.engagedType;
  });
  for (const a of Object.values(annotations)) {
    if (!a.block_id) continue;
    // querySelector returns the first match in document order — the
    // <section>. For sequence diagrams, the SVG <g class="step-row">
    // children also carry data-block-id, so an explicit second query is
    // needed to flag the specific step that has the draft.
    const block = document.querySelector(`[data-block-id="${cssEsc(a.block_id)}"]`);
    if (block) block.dataset.engagedType = a.type;
    if (a.step_id) {
      const step = document.querySelector(
        `[data-block-id="${cssEsc(a.block_id)}"][data-step-id="${cssEsc(a.step_id)}"]`
      );
      if (step) step.dataset.engagedType = a.type;
    }
  }
}

function occurrences(haystack, needle) {
  if (!needle) return 0;
  let n = 0, i = 0;
  while ((i = haystack.indexOf(needle, i)) !== -1) { n++; i += needle.length; }
  return n;
}

function blockSnippet(blockId) {
  if (!blockId) return "";
  const block = document.querySelector(`[data-block-id="${cssEsc(blockId)}"]`);
  if (!block) return "";
  const clone = block.cloneNode(true);
  const text = (clone.textContent || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length > 60 ? text.slice(0, 59).trimEnd() + "…" : text;
}

// Open (or reuse) the inline comment editor for a block (optionally scoped to
// a data-annotate-id region by stepId). Shared by the selection menu and
// mockup iframe clicks (where a data-annotate-id slug is forwarded via
// postMessage). `selection`, when given, is cleared
// once the draft is created.
function openAnnotation(block, type, opts) {
  opts = opts || {};
  const stepId = opts.stepId != null ? opts.stepId : null;
  const selectedText = opts.selectedText || "";
  const sel = opts.selection || null;
  // Single input per target: if a draft already exists for this
  // (block, step), reuse it instead of stacking a second card, keeping any
  // text already typed. There is no comment↔reject intent switch: Claude
  // weighs every comment on its merits, so disagreement is just words.
  const blockId = block.dataset.blockId;
  const norm = (s) => (s == null ? null : s);
  const existingId = Object.keys(annotations).find((k) => {
    const x = annotations[k];
    return x.block_id === blockId && norm(x.step_id) === norm(stepId);
  });

  // Single-flight: refuse to open a second editor while one is already open
  // for a different target. Not gated on BUSY — the editor pins its
  // comment into the local round via AnnotateSubunits.pinComment(), which
  // never touches the network, so an in-flight round is not a reason to
  // refuse opening it.
  if (!existingId) {
    // Drop any empty draft first — otherwise a stray click on one block
    // makes every other block unclickable until its × is found and pressed.
    for (const [k, v] of Object.entries(annotations)) {
      if (isEmptyDraft(v)) delete annotations[k];
    }
    if (Object.keys(annotations).length > 0) {
      revealOpenDraft();
      return;
    }
  }

  const id = existingId || `a-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  const annot = annotations[id] || { block_id: blockId, step_id: stepId, comment: "" };
  annot.type = type;
  // A fresh selection re-scopes the card; otherwise keep the existing scope.
  if (selectedText) {
    annot.selected_text = selectedText;
    const blockText = block.textContent;
    delete annot.prefix;
    delete annot.suffix;
    if (occurrences(blockText, selectedText) > 1) {
      const idx = blockText.indexOf(selectedText);
      annot.prefix = blockText.slice(Math.max(0, idx - 20), idx);
      annot.suffix = blockText.slice(idx + selectedText.length, idx + selectedText.length + 20);
    }
  } else if (!existingId) {
    annot.selected_text = "";
  }
  annotations[id] = annot;
  saveDrafts();
  renderComments();
  applyEngagedStyling();
  if (sel) sel.removeAllRanges();
  focusComment(id);
}

// ── Block loading and rendering ────────────────────────────────────────────

// ── Code coloured late ──────────────────────────────────────────────────
// The highlighter loads after the page has painted, and each grammar the
// first time some code asks for it (code-paint.js). Code rendered before
// then goes out plain; when code-paint.js says what it was waiting for has
// arrived, that code is coloured where it stands. Only the text of each
// line is replaced — the same characters, now in coloured spans — so the
// section, its rows, its marks (overlays beside the line, never inside it)
// and anything the reader was doing there are left alone.
//
// `later(el, paint)`: `el` was shown plain; `paint()` colours it, and
// answers false when it still cannot.
const plainCode = new Set();
const codeMisses = () => (window.CodePaint && CodePaint.misses ? CodePaint.misses() : 0);
function later(el, paint) {
  el._paint = paint;
  plainCode.add(el);
}

// A run of `.cp-line` cells and the lines they show → coloured rows.
function paintRowsLater(cells, texts, opts) {
  return () => {
    const rows = CodePaint.rows(texts, opts);
    if (!rows) return false;
    cells.forEach((cell, i) => { cell.innerHTML = rows[i]; });
    return true;
  };
}

function repaintCode() {
  let any = false;
  for (const el of [...plainCode]) {
    if (!el.isConnected) { plainCode.delete(el); continue; }
    if (el._paint()) { plainCode.delete(el); any = true; }
  }
  // Fences come out of markdown-it as HTML, so they carry their language
  // in the markup instead.
  document.querySelectorAll("code.sk-fence[data-plain]").forEach((code) => {
    const painted = CodePaint.paint(code.textContent, { lang: code.dataset.lang });
    if (painted === null) return;
    code.innerHTML = painted;
    delete code.dataset.plain;
    any = true;
  });
  if (!any) return;
  // Text nodes were replaced under any reader's mark or highlight.
  window.AnnotateSubunits?.paintSpans?.();
  repaintHighlights();
}
document.addEventListener("codepaint:ready", repaintCode);

// Syntax-highlight fenced code, through CodePaint (Shiki). Returning a full
// `<pre><code class="sk-fence">` makes markdown-it use it verbatim (it only
// wraps when the hook returns a non-<pre> string). An untagged fence, or a
// tag no grammar claims, is shown plain on the same dark ground: Shiki does
// not guess a language, and a guess is what used to paint prose as code.
// An empty return falls back to markdown-it's own escaped rendering — only
// when the highlighter itself failed to load.
function highlightFence(str, lang) {
  if (!window.CodePaint) return "";
  const tag = String(lang || "").trim().split(/\s+/)[0];
  const misses = codeMisses();
  const painted = CodePaint.paint(str.replace(/\n$/, ""), { lang: tag });
  const inner = painted !== null ? painted
    : str.replace(/\n$/, "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const cls = "sk-fence" + (tag ? " language-" + tag.replace(/[^\w-]/g, "") : "");
  // Plain only until its grammar loads: say which, for repaintCode.
  const wait = painted === null && codeMisses() > misses
    ? ' data-plain="1" data-lang="' + tag.replace(/&/g, "&amp;").replace(/"/g, "&quot;") + '"' : "";
  return '<pre><code class="' + cls + '"' + wait + ">" + inner + "</code></pre>";
}

const blockMd = (typeof window.markdownit === "function")
  ? window.markdownit({ html: true, linkify: true, typographer: false,
                        breaks: false, highlight: highlightFence })
  : null;

// Indented code blocks are disabled on purpose.  With html:true, Claude
// writes free-form HTML into blocks, and readable HTML is indented — but
// CommonMark turns any line indented 4+ spaces into a code block, so a
// hand-formatted <div> tree renders as its own source.  A blank line makes
// it worse: it closes the HTML block, and everything after it is indented,
// so half a diagram silently becomes a listing.  Nothing here needs
// indented code — every code sample we emit is fenced (see highlightFence),
// and fences are a separate rule that stays enabled.
if (blockMd) blockMd.disable("code");

// Conservative sanitizer for HTML that lands in a block via markdown-it
// (now html: true so Claude can emit free-form HTML).  Threat model is
// "defend against accidents", not a hostile author — Claude is the only
// writer of blocks.json — but we strip the obvious script/handler vectors
// so a broken response can't break the page.
const SAN_DISALLOWED_TAGS = new Set([
  "SCRIPT", "IFRAME", "OBJECT", "EMBED", "LINK", "META", "STYLE", "BASE", "FORM",
]);
function sanitizeFreeHtml(root) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  const toRemove = [];
  let node;
  while ((node = walker.nextNode())) {
    // tagName is uppercase for HTML elements but lowercase for SVG
    // descendants (different namespace) — normalise before checking
    // so `<svg><script>` is caught the same as a top-level `<script>`.
    if (SAN_DISALLOWED_TAGS.has(node.tagName.toUpperCase())) {
      toRemove.push(node);
      continue;
    }
    for (const attr of [...node.attributes]) {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on")) {
        node.removeAttribute(attr.name);
        continue;
      }
      if ((name === "href" || name === "src" || name === "xlink:href") &&
          /^\s*javascript:/i.test(attr.value)) {
        node.removeAttribute(attr.name);
      }
    }
  }
  for (const n of toRemove) n.remove();
}

async function loadAndRenderBlocks() {
  if (!proseEl || !blockMd) return;
  let data;
  try {
    const r = await fetch(BASE + "raw", { cache: "no-store" });
    if (!r.ok) return;
    data = await r.json();
  } catch (_) {
    return;
  }
  if (window.AnnotateGlossary) {
    window.AnnotateGlossary.setGlossary(data.glossary || []);
    // Seed the poll-loop's change-detector so the first tick doesn't see
    // undefined→[...] and fire a needless refreshAll() that collapses any
    // in-progress text selection.
    window.AnnotateGlossary._lastGlossary = data.glossary || [];
  }
  refreshPageState();
  proseEl.replaceChildren();
  for (const blk of (data.blocks || [])) {
    const section = createBlockSection(blk);
    proseEl.appendChild(section);
  }
  // A pending block mark is painted onto its section, and every section
  // above was built detached, where painting finds nothing. Paint now.
  window.AnnotateSubunits?.repaintBlocks();
  renderComments();
  applyEngagedStyling();
  document.dispatchEvent(new CustomEvent("annotate:rendered"));
}

// Header title for a block's card. Claude may author a `title`; otherwise we
// derive one from the content (first heading, else first sentence/line).
// The rule lives in block-title.js so it can be executed by a test; see the
// header there for why a source-string check could not catch the defect it
// fixes. entry.js loads that file before this one.
function blockTitle(blk) {
  return window.AnnotateBlockTitle.blockTitle(blk);
}

function setCardTitle(section, blk) {
  const el = section.querySelector(".card-title");
  if (el) el.textContent = blockTitle(blk);
}

// Render a choice block's interactive body: selectable option cards and an
// optional note field. A card click toggles selection (single-select moves
// it). There is no Submit here: the answer is a round mark, kept in step
// with every click and keystroke, and it goes to Claude with everything
// else when the round dock's Submit is pressed. That is what lets one page
// ask several questions and get all the answers back in one go. Note-only
// means "none of these — here's my direction".
function renderChoice(section, content, blk) {
  const spec = blk.spec || {};
  const multi = !!spec.multiSelect;
  const options = Array.isArray(spec.options) ? spec.options : [];
  // A queue is a run of choice sections sharing this; choice-queue.js reads it.
  if (typeof spec.group === "string" && spec.group.trim()) section.dataset.group = spec.group;
  else delete section.dataset.group;

  const wrap = document.createElement("div");
  wrap.className = "choice-block";

  // The question is shown in the card header (derived from spec.question by
  // blockTitle) — don't repeat it in the body.

  const list = document.createElement("div");
  list.className = "choice-options";
  list.setAttribute("role", multi ? "group" : "radiogroup");
  const titleId = section.querySelector(".card-title")?.id;
  if (titleId) list.setAttribute("aria-labelledby", titleId);
  const cards = [];
  const selected = new Set();

  const setChecked = (card, on) => {
    card.classList.toggle("selected", on);
    card.setAttribute("aria-checked", String(on));
  };
  const toggleAt = (idx, { advance = true } = {}) => {
    const opt = options[idx];
    if (selected.has(opt.id)) {
      selected.delete(opt.id);
      setChecked(cards[idx], false);
    } else {
      if (!multi) {
        selected.clear();
        cards.forEach(c => setChecked(c, false));
      }
      selected.add(opt.id);
      setChecked(cards[idx], true);
    }
    syncRoving();
    saveAnswer();
    // A pick, not a clear: the queue moves on to the next undecided question.
    // A multi-select question is not answered by its first pick, so it waits for Next.
    // Arrows pass advance:false: they move through the answers, not past the question.
    if (advance && !multi && selected.has(opt.id)) {
      document.dispatchEvent(new CustomEvent("annotate:choice-picked",
        { detail: { blockId: blk.id } }));
    }
  };
  // A single-select is a radio group, and a radio group is ONE tab stop:
  // the checked option, or the first when none is. Each option used to be
  // its own stop, so Tab walked every answer to a question on the way past
  // it. Checkboxes keep one stop each, which is what a checkbox group is.
  function syncRoving() {
    if (multi) return;
    const at = Math.max(0, options.findIndex(o => selected.has(o.id)));
    cards.forEach((c, j) => { c.tabIndex = j === at ? 0 : -1; });
  }
  // Arrows in a radio group move the selection with the focus; in a
  // checkbox group they only move the focus. A click still toggles, so a
  // single-select can be cleared by clicking its choice again.
  const arrowTo = (to) => {
    if (!multi && !selected.has(options[to].id)) toggleAt(to, { advance: false });
    cards[to].focus();
  };

  options.forEach((opt, idx) => {
    const card = document.createElement("div");
    card.className = "choice-option";
    card.tabIndex = 0;
    card.setAttribute("role", multi ? "checkbox" : "radio");
    card.setAttribute("aria-checked", "false");
    const textWrap = document.createElement("div");
    textWrap.className = "choice-option-text";
    const head = document.createElement("span");
    head.className = "choice-option-head";
    const label = document.createElement("span");
    label.className = "choice-option-label";
    label.textContent = opt.label || opt.id;
    head.appendChild(label);
    if (opt.recommended) {
      const badge = document.createElement("span");
      badge.className = "choice-badge";
      badge.textContent = "recommended";
      head.appendChild(badge);
    }
    textWrap.appendChild(head);
    if (opt.description) {
      const desc = document.createElement("span");
      desc.className = "choice-option-desc";
      desc.textContent = opt.description;
      textWrap.appendChild(desc);
    }
    // An option may carry content: code, a table, prose. It renders through
    // the same markdown-it and Shiki path as a markdown block, so a fenced
    // java sample in an option looks exactly like one in the page.
    if (typeof opt.markdown === "string" && opt.markdown.trim() && blockMd) {
      const optBody = document.createElement("div");
      optBody.className = "choice-option-body";
      optBody.id = `choice-body-${blk.id}-${opt.id}`;
      optBody.innerHTML = blockMd.render(opt.markdown);
      sanitizeFreeHtml(optBody);
      textWrap.appendChild(optBody);
      card.classList.add("has-body");
      card.setAttribute("aria-describedby", optBody.id);
    }
    card.appendChild(textWrap);
    // The body is content the reader reads and copies from. A click in it
    // that ends a selection, selects a word, or lands on a link, is not a
    // pick. The label and head always pick: they are user-select:none, so a
    // click there leaves an earlier selection standing.
    card.addEventListener("click", (e) => {
      const inBody = e.target.closest && e.target.closest(".choice-option-body");
      if (inBody) {
        if (e.target.closest("a[href]")) return;
        if (e.detail > 1) return;
        const sel = window.getSelection && window.getSelection();
        if (sel && !sel.isCollapsed) return;
      }
      toggleAt(idx);
    });
    card.addEventListener("keydown", (e) => {
      // A focused link in the body keeps its own Enter and Space.
      if (e.target !== card) return;
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        toggleAt(idx);
      } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
        e.preventDefault();
        arrowTo((idx + 1) % cards.length);
      } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
        e.preventDefault();
        arrowTo((idx - 1 + cards.length) % cards.length);
      }
    });
    cards.push(card);
    list.appendChild(card);
  });
  wrap.appendChild(list);

  // Digit shortcuts 1..9 toggle the corresponding option while focus is
  // anywhere in the block except the note field (typing digits there is
  // just typing).
  wrap.addEventListener("keydown", (e) => {
    if (e.target === note) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const n = Number(e.key);
    if (Number.isInteger(n) && n >= 1 && n <= options.length) {
      e.preventDefault();
      toggleAt(n - 1);
    }
  });

  const footer = document.createElement("div");
  footer.className = "choice-footer";
  const note = document.createElement("textarea");
  note.className = "choice-note";
  note.rows = 1;
  note.placeholder = "Add a note (optional) — or answer in your own words";
  // A detached textarea measures scrollHeight 0, and the block is still
  // detached on its first render, so fit only once it is on the page.
  const fitNote = () => {
    note.style.height = "auto";
    if (note.isConnected) note.style.height = note.scrollHeight + "px";
  };
  note.addEventListener("input", () => {
    fitNote();
    saveAnswer();
  });
  note.addEventListener("keydown", (e) => {
    // Cmd/Ctrl+Enter submits the round — plain Enter stays a newline, same
    // convention as the general and card composers (a note may be a
    // multi-line answer, e.g. a numbered list).
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      const btn = document.getElementById("round-submit");
      if (btn && !btn.disabled) btn.click();
    }
  });

  function saveAnswer() {
    const picked = options.filter(o => selected.has(o.id));
    // Untrimmed: the stored note is what repaints the box after a rewrite,
    // and a trimmed copy ate the newline the reader had just typed. The
    // round trims it on the way out.
    window.AnnotateSubunits?.setChoice(blk.id, picked.map(o => o.id),
      picked.map(o => o.label || o.id), note.value);
  }

  // Paint the stored answer. Runs on every render, since a poll re-renders
  // the block, and again when the dock removes the answer.
  function loadAnswer() {
    const m = window.AnnotateSubunits?.choiceMark(blk.id);
    selected.clear();
    const stored = (m && m.selected_options) || [];
    // Claude may rewrite the question with a different slate. An answer
    // naming an option that no longer exists would go out in the round
    // while no card on the page shows it picked.
    const live = new Set(options.map(o => o.id));
    for (const id of stored) if (live.has(id)) selected.add(id);
    options.forEach((o, i) => setChecked(cards[i], selected.has(o.id)));
    syncRoving();
    note.value = (m && m.text) || "";
    requestAnimationFrame(fitNote);
    if (m && selected.size !== stored.length) saveAnswer();
  }
  section.syncChoice = loadAnswer;

  footer.append(note);
  wrap.appendChild(footer);
  content.appendChild(wrap);
  loadAnswer();
}

// ── Mockup kind: full-fidelity HTML in a sandboxed iframe ───────────────────
// Live registry of mockup iframes, so the single boot-level message handler
// can match an inbound postMessage to the iframe that sent it by object
// identity. The frame's origin is the string "null" and must NOT be trusted.
const mockupFrames = new Set();

window.addEventListener("message", (ev) => {
  const d = ev.data;
  if (!d || (d.type !== "annotate:height" && d.type !== "annotate:click")) return;
  // Authenticate by object identity: a sandboxed srcdoc frame's origin is the
  // string "null" and must NOT be trusted. Find which still-connected mockup
  // iframe actually sent this message.
  let target = null;
  for (const f of Array.from(mockupFrames)) {
    if (!f.isConnected) { mockupFrames.delete(f); continue; }  // prune stale
    if (f.contentWindow === ev.source) target = f;             // identity gate
  }
  if (!target) return;
  if (d.type === "annotate:height") {
    const h = Number(d.h);
    if (!Number.isFinite(h)) return;                           // ignore garbage
    target.style.height = Math.min(Math.max(h, 20), 20000) + "px"; // clamp
    return;
  }
  // annotate:click — a click on a [data-annotate-id] region inside the mock.
  // Opens a comment scoped to that slug, reusing the whole free-HTML contract.
  if (typeof d.id !== "string" || !d.id.trim() || d.id.length > 256) return;
  const section = target.closest("section.block");
  if (section) openAnnotation(section, "comment", { stepId: d.id });
});

const MOCKUP_CSP =
  '<meta http-equiv="Content-Security-Policy" content="' +
  "default-src 'none'; img-src data:; style-src 'unsafe-inline'; " +
  "script-src 'unsafe-inline'; font-src data:; connect-src 'none'; " +
  "form-action 'none'; base-uri 'none'\">";

// Trusted, host-injected. (1) Reports content height up so the host can size
// the iframe (on observe, DOMContentLoaded, load, and late <img> loads).
// (2) Forwards clicks on [data-annotate-id] regions up to the host so it can
// open a comment scoped to that region — iframe clicks don't bubble out.
const MOCKUP_BRIDGE =
  "<scr" + "ipt>(function(){function p(){parent.postMessage(" +
  "{type:'annotate:height',h:document.documentElement.scrollHeight},'*');}" +
  "try{new ResizeObserver(p).observe(document.documentElement);}catch(e){}" +
  "document.addEventListener('DOMContentLoaded',p);" +
  "window.addEventListener('load',p,true);" +
  "document.addEventListener('click',function(e){" +
  "var el=e.target&&e.target.closest&&e.target.closest('[data-annotate-id]');" +
  "if(el)parent.postMessage({type:'annotate:click'," +
  "id:el.getAttribute('data-annotate-id')},'*');});" +
  "p();})();</scr" + "ipt>";

// Drop any mockup iframes under `root` from the registry before the node is
// detached, so the Set never holds stale frames between message sweeps.
function untrackMockupFrames(root) {
  root.querySelectorAll("iframe.mockup-frame").forEach((f) => mockupFrames.delete(f));
}

function renderMockup(content, blk) {
  const html = (blk.spec && blk.spec.html) || "";
  if (!html) {
    content.innerHTML = '<div class="mockup-missing">mockup unavailable</div>';
    return;
  }
  const iframe = document.createElement("iframe");
  iframe.className = "mockup-frame";
  iframe.setAttribute("sandbox", "allow-scripts");   // NEVER allow-same-origin
  iframe.setAttribute("scrolling", "no");
  iframe.style.height = "60px";                       // placeholder until bridge reports
  iframe.srcdoc =
    '<!DOCTYPE html><html><head><meta charset="utf-8">' + MOCKUP_CSP +
    "<style>html,body{margin:0;padding:0}</style></head><body>" +
    html + MOCKUP_BRIDGE + "</body></html>";
  mockupFrames.add(iframe);
  content.appendChild(iframe);
}

// ── pflow source pane ──────────────────────────────────────────────────────

// Highlight pflow source. An empty return means the highlighter is missing,
// and the caller falls back to plain text rather than showing markup.
// pflow's tags are comments to Python, so the theme paints them all one
// comment colour; the tag comments are re-marked so the side-channel
// (cache/gate/note/ref) reads as a channel.
const PFLOW_TAG = /^#\s*(?:[!?]|(?:id|cache|gate|note|ref)\s*:)/;
function highlightPflow(src) {
  if (!window.CodePaint) return "";
  const html = CodePaint.paint(src, {
    lang: "python",
    wrap: (t, text) => (PFLOW_TAG.test(t.content) ? '<span class="pflow-tag">' + text + "</span>" : text),
  });
  return html === null ? "" : html;
}
