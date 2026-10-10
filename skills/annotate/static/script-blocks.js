// annotate page code, part 4 of 9 (see script.js): one block's part of
// the document — the code column, the pflow source pane, diagram layouts and
// views, and the section itself, with its heading and fold.

// The band of panes under one block's prose, or null when the block cites
// no code. An anchorless block renders exactly as annotate does today:
// full-width prose, nothing under it.
function renderCodeColumn(blk) {
  // I4: check_anchors already refuses a mockup block's anchors at push
  // time, but the render path serves strangers on the read-only link --
  // defence in depth belongs here too, not only in the check. A mockup
  // renders in a sandboxed iframe and has nowhere to put a pane.
  if (blk.kind === "mockup") return null;
  const panes = Array.isArray(blk.code) ? blk.code : [];
  if (!panes.length) return null;

  const col = document.createElement("div");
  col.className = "code-col";
  panes.forEach((p) => col.appendChild(renderCodePane(p)));
  return col;
}

// The reading highlighter paints ranges over block prose from outside the
// DOM, so it has to be re-applied whenever that prose is replaced. Called
// from here rather than from a MutationObserver inside the highlighter: this
// is the point where a render is FINISHED, which an observer cannot know.
function repaintHighlights() {
  const hl = window.annotateHighlighter;
  if (hl && typeof hl.repaint === "function") hl.repaint();
}

// Run on every full render and every poll: re-reads the settings (another
// tab may have changed a global one) and repaints the highlighter.
function refreshPageState() {
  applyViewControls();
  repaintHighlights();
}

// A flowchart authored as pflow ships the source it was compiled from. Render
// it under the chart, line-addressable: every line that produced a node
// carries that node's id, so hovering either view lights the other and the
// reader can see which line drew which shape. The line used to be a comment
// target too; it is not any more (see the createBlockSection note on why the
// granular scope was withdrawn from pictures).
function renderPflowSource(blk) {
  const spec = blk.spec || {};
  const src = String(spec.source || "").replace(/\n+$/, "");
  if (!src) return null;

  const wrap = document.createElement("div");
  wrap.className = "pflow";

  const head = document.createElement("div");
  head.className = "pflow-head";
  const label = document.createElement("span");
  label.className = "pflow-label";
  label.textContent = "source";
  const hint = document.createElement("span");
  hint.className = "pflow-hint";
  hint.textContent = "hover a line to light the step it draws";
  head.append(label, hint);

  const byLine = new Map();
  (spec.nodes || []).forEach((n) => {
    if (n && n.line) byLine.set(Number(n.line), n.id);
  });

  const lines = src.split("\n");
  const misses = codeMisses();
  const painted = highlightPflow(src);
  const paintedLines = painted ? CodePaint.splitRows(painted) : null;
  const cells = [];

  // `.sk-fence` on the body, not on a <pre><code>: it takes the fence ground
  // and base colour (each token carries its own colour regardless), and it
  // keeps `main.prose pre code.sk-fence` — which sets its own font-size and
  // line-height for fenced code — from reaching in here and breaking the rows.
  const body = document.createElement("div");
  body.className = "pflow-body sk-fence";

  lines.forEach((line, i) => {
    const row = document.createElement("div");
    row.className = "pflow-row";
    const num = document.createElement("span");
    num.className = "pflow-num";
    num.setAttribute("aria-hidden", "true");
    num.textContent = String(i + 1);
    const text = document.createElement("span");
    text.className = "pflow-line";
    if (paintedLines) text.innerHTML = paintedLines[i] || "";
    else text.textContent = line;
    cells.push(text);
    // A line that produced a node carries its id, which is what pairs the
    // row with the shape on hover. Lines that produced nothing stay inert.
    // Neither is clickable: the comment on a picture is whole-block now.
    const nodeId = byLine.get(i + 1);
    if (nodeId) {
      row.dataset.nodeId = nodeId;
      row.classList.add("is-live");
    }
    row.append(num, text);
    body.appendChild(row);
  });

  wrap.append(head, body);
  if (!paintedLines && codeMisses() > misses) {
    later(body, () => {
      const html = highlightPflow(src);
      if (!html) return false;
      const rows = CodePaint.splitRows(html);
      cells.forEach((cell, i) => { cell.innerHTML = rows[i] || ""; });
      return true;
    });
  }
  return wrap;
}

// A block that laid out cleanly in more than one way ships every rendering
// and lets the reader pick. The choice is theirs alone: it lives in
// localStorage, is never sent to the daemon, and never reaches another
// viewer. Storage can throw outright in a private window or with site data
// blocked, so every access is guarded and an unreadable store simply means
// the block opens on its default.
//
// Keyed by response as well as block. Block ids repeat across documents
// (every document's first block is section-1), so a key of the block id
// alone carried a layout picked in one document into every other one.
const FLAVOUR_KEY = "annotate.flavour";
const VIEW_KEY = "annotate.flowview";

function choiceKey(prefix, blockId) {
  const rid = document.body.dataset.responseId || "default";
  return `${prefix}:${rid}:${blockId}`;
}

function readChoice(prefix, blockId) {
  try {
    return window.localStorage.getItem(choiceKey(prefix, blockId));
  } catch (e) {
    return null;
  }
}

function writeChoice(prefix, blockId, name) {
  try {
    window.localStorage.setItem(choiceKey(prefix, blockId), name);
  } catch (e) {
    /* per-viewer convenience only — losing it costs nothing */
  }
}

function flavourLabel(name) {
  if (name === "all") return "All";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

// Paint a flowchart block: the server SVG, plus the source pane when the
// block was authored as pflow, plus the layout control when it shipped more
// than one rendering. Shared by create and update so an in-place refresh
// cannot leave one without the others.
function paintFlowchart(content, blk) {
  const svgs = blk.svgs || {};
  // Views win over layout flavours when a block ships both: a view changes
  // which edges are drawn, which is a question the reader asked, while a
  // flavour only changes how the same edges are arranged.
  const viewNames = blk.views || [];
  const isViews = viewNames.length > 1;
  const names = isViews ? viewNames : blk.flavours || [];
  const key = isViews ? VIEW_KEY : FLAVOUR_KEY;
  const label = isViews ? "Diagram view" : "Diagram layout";

  function buildControl(current) {
    const wrap = document.createElement("div");
    wrap.className = isViews ? "flow-flavours flow-views" : "flow-flavours";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", label);
    names.forEach((name) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = flavourLabel(name);
      if (isViews) b.dataset.view = name;
      else b.dataset.flavour = name;
      if (name === current) b.setAttribute("aria-pressed", "true");
      else b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => {
        writeChoice(key, blk.id, name);
        paint(name);
      });
      wrap.appendChild(b);
    });
    return wrap;
  }

  const paint = (name) => {
    // Trusted server output — deliberately bypasses sanitizeFreeHtml so the
    // class/data-* hit targets survive.
    content.innerHTML = (name && svgs[name]) || blk.svg || "";
    if (names.length > 1) content.prepend(buildControl(name));
    const source = renderPflowSource(blk);
    if (source) content.appendChild(source);
  };

  let chosen = names.length > 1 ? readChoice(key, blk.id) : null;
  if (names.indexOf(chosen) === -1) chosen = names[0] || null;
  paint(chosen);
}

// Hovering either view lights the other: the id lives on the SVG node and on
// the source line alike, so one selector reaches both.
function linkPflowHover(content) {
  const clear = () => {
    content.querySelectorAll(".is-node-active").forEach((el) => {
      el.classList.remove("is-node-active");
    });
  };
  content.addEventListener("mouseover", (ev) => {
    const el = ev.target.closest && ev.target.closest("[data-node-id]");
    clear();
    if (!el || !content.contains(el)) return;
    content.querySelectorAll(`[data-node-id="${cssEsc(el.dataset.nodeId)}"]`)
      .forEach((m) => m.classList.add("is-node-active"));
  });
  content.addEventListener("mouseleave", clear);
}

// A sequence block is two halves: the grid (`blk.svg`) and the numbered key
// beneath it (`blk.key`). The grid carries arrows and badges and no words at
// all, so painting the svg alone leaves a picture of unexplained circles —
// both halves go in together, always.
function paintSequence(content, blk) {
  content.innerHTML = (blk.svg || "") + (blk.key || "");
}

// Badge ⇄ key pairing. They pair on data-step-id, which is also what a
// comment anchors to, so lighting a step lights whatever a comment marked.
// Delegated from .block-content, which survives updateBlockContent's
// innerHTML swap — binding to the badges themselves would go stale on the
// first repaint.
function linkSequenceKey(content) {
  const clear = () => {
    content.querySelectorAll(".is-linked").forEach((el) => el.classList.remove("is-linked"));
  };
  const select = (stepId, scroll) => {
    const row = content.querySelector(`.seq-key-row[data-step-id="${cssEsc(stepId)}"]`);
    const grid = content.querySelector(`.step-row[data-step-id="${cssEsc(stepId)}"]`);
    // A second click on the same step lets go, so a reader is never stuck
    // with a highlight they cannot dismiss from the thing they clicked.
    if (row && row.classList.contains("is-linked")) { clear(); return; }
    clear();
    if (row) row.classList.add("is-linked");
    if (grid) grid.classList.add("is-linked");
    if (scroll && row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  const handle = (ev, el) => {
    ev.stopPropagation();
    select(el.dataset.stepId, el.classList.contains("badge-hit"));
  };
  content.addEventListener("click", (ev) => {
    const el = ev.target.closest && ev.target.closest(".badge-hit, .seq-key-row");
    if (el && content.contains(el)) handle(ev, el);
    else clear();
  });
  content.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { clear(); return; }
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const el = ev.target.closest && ev.target.closest(".badge-hit, .seq-key-row");
    if (!el || !content.contains(el)) return;
    ev.preventDefault();
    handle(ev, el);
  });
}

function createBlockSection(blk) {
  const section = document.createElement("section");
  section.className = "block";
  section.dataset.blockId = blk.id;
  section.dataset.version = String(blk.version ?? 1);
  const kind = blk.kind || "markdown";
  section.dataset.kind = kind;
  // The reader's own words in this block (edit.js paints them).
  section._mine = Array.isArray(blk.mine) ? blk.mine : [];
  // A part of one document: no box and no header bar. Its name for screen
  // readers and the round dock is the derived title; what shows is only an
  // authored one (blockLabel). Focus comes back here when a comment or the
  // editor closes, so the section itself can take it.
  section.setAttribute("aria-label", blockTitle(blk));
  section.tabIndex = -1;
  section.appendChild(blockLabel(blk));

  const body = document.createElement("div");
  body.className = "block-body";
  const content = document.createElement("div");
  content.className = "block-content";
  if (kind === "sequence") {
    // Server pre-rendered both halves; inject as-is.
    paintSequence(content, blk);
    linkSequenceKey(content);
    // Still no comment-on-click: a picture is commented as a whole, from its
    // heading, for the same reason flowchart lost its node handler
    // below. What linkSequenceKey binds is not a way into the composer — it
    // pairs a badge with its key entry and nothing else. The `data-step-id`
    // hit targets stay on the rows: they anchor comments made before that
    // rule, and applyEngagedStyling still paints the row they target.
  } else if (kind === "flowchart") {
    // Server pre-rendered the hand-built SVG, plus the pflow source pane when
    // the block carries one. Both views hang their hit targets off
    // data-node-id, so the one listener below serves either.
    paintFlowchart(content, blk);
    linkPflowHover(content);
    // A picture is commented as a whole, from its heading — never per
    // node. The node click handler that used to live here was withdrawn
    // because a node's `ref` line is painted accent-coloured and underlined
    // whether or not the spec gave it an href (`.annotate-flow .flow-ref`),
    // so a file reference with no href reads as a jump-to-source link and
    // behaved as a comment target: the click missed the absent anchor and
    // opened the composer instead. Reaching for a file and getting an
    // editor is the whole complaint, and no amount of hit-target tuning
    // fixes a link that isn't one.
    //
    // What survives is navigation: an in-page cross-block anchor
    // (href="#<block-id>") smooth-scrolls to that block, and any other
    // anchor (e.g. a jetbrains:// code ref) is left to navigate normally.
    // Listener lives on content so updateBlockContent's innerHTML swap
    // doesn't drop it.
    content.addEventListener("click", (ev) => {
      const anchor = ev.target.closest && ev.target.closest("a[href]");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href.startsWith("#")) return;
      ev.preventDefault();
      const target = document.querySelector(
        `[data-block-id="${cssEsc(href.slice(1))}"]`
      );
      if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  } else if (kind === "choice") {
    renderChoice(section, content, blk);
  } else if (kind === "mockup") {
    // Trusted Claude HTML in a sandboxed iframe; deliberately bypasses
    // sanitizeFreeHtml (the sandbox is the isolation boundary instead).
    renderMockup(content, blk);
  } else if (kind === "explain") {
    renderExplain(content, blk);
  } else {
    // Markdown path — markdown-it now allows inline HTML (`html: true`);
    // sanitize the rendered tree before glossary decoration.
    content.innerHTML = blockMd ? blockMd.render(blk.markdown || "") : (blk.markdown || "");
    sanitizeFreeHtml(content);
    if (window.AnnotateGlossary) window.AnnotateGlossary.decorate(content);
  }
  body.appendChild(content);

  const codeCol = renderCodeColumn(blk);
  if (codeCol) {
    section.dataset.hasCode = "1";
    body.appendChild(codeCol);
  }

  section.appendChild(body);
  return section;
}

// The part's visible name. An authored title is an h2 with the fold button
// before it. A part without one gets an empty line instead, which shows only
// when a mark or a change chip needs a place to sit.
function blockLabel(blk) {
  const title = visibleTitle(blk);
  const el = document.createElement(title ? "h2" : "div");
  el.className = title ? "block-label block-heading" : "block-label block-meta";
  el.id = `block-label-${blk.id}`;
  if (!title) return el;
  const fold = document.createElement("button");
  fold.type = "button";
  fold.className = "fold-btn";
  fold.textContent = "▾";
  fold.setAttribute("aria-label", "Fold");
  fold.setAttribute("aria-expanded", "true");
  fold.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const section = el.closest("section.block");
    setFolded(blk.id, !section.classList.contains("collapsed"));
  });
  const text = document.createElement("span");
  text.className = "block-heading-text";
  text.textContent = title;
  el.append(fold, text);
  return el;
}

// A label of the same shape is updated in place, so the chip and the "what
// changed" toggle a change put on it (and the fold button) survive a
// re-render. Only a title gained or lost replaces the element.
function setBlockLabel(section, blk) {
  const old = section.querySelector(".block-label");
  const fresh = blockLabel(blk);
  const sameShape = old && old.classList.contains("block-heading")
    === fresh.classList.contains("block-heading");
  if (sameShape) {
    const text = old.querySelector(".block-heading-text");
    if (text) text.textContent = fresh.querySelector(".block-heading-text").textContent;
  } else if (old) old.replaceWith(fresh);
  else section.prepend(fresh);
  section.setAttribute("aria-label", blockTitle(blk));
}

function focusHome(section) {
  if (!section || !document.contains(section)) return;
  (section.querySelector(".fold-btn") || section).focus({ preventScroll: true });
}

function visibleTitle(blk) {
  return window.AnnotateBlockTitle.visibleTitle(blk);
}

function collapseKey(blockId) {
  const rid = (document.body.dataset.responseId || "default");
  return `annotate.collapsed:${rid}:${blockId}`;
}

function readFolded(blockId) {
  try { return localStorage.getItem(collapseKey(blockId)) === "1"; } catch (_) { return false; }
}

function setFolded(blockId, on) {
  try { localStorage.setItem(collapseKey(blockId), on ? "1" : "0"); } catch (_) {}
  applyFolds();
}

// One part at a time for now: a titled part folds its own body. Task 4 makes
// a heading fold the untitled parts after it too.
function applyFolds() {
  document.querySelectorAll("main.prose section.block[data-block-id]").forEach((s) => {
    const titled = !!s.querySelector(".block-heading");
    const on = titled && readFolded(s.dataset.blockId);
    s.classList.toggle("collapsed", on);
    const b = s.querySelector(".fold-btn");
    if (b) {
      b.textContent = on ? "▸" : "▾";
      b.setAttribute("aria-label", on ? "Unfold" : "Fold");
      b.setAttribute("aria-expanded", String(!on));
    }
  });
}
document.addEventListener("annotate:rendered", applyFolds);
