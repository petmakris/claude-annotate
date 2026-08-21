/* Reading highlighter — drag-select prose and the stretch keeps a marker
 * background, so the page shows a trail of what has already been read.
 * Front-end only: nothing here reaches the server.
 *
 * Painted with the CSS Custom Highlight API, NOT by wrapping text in spans.
 * That is the load-bearing choice. Block content is written with innerHTML
 * and then walked twice more -- subunits.js wraps sentences, search.js
 * inserts <mark class="search-hit"> -- so wrapper elements would be shredded
 * by one and would shred the other. A registered Highlight paints ranges from
 * outside the DOM entirely, which also means an export cannot inherit one
 * reader's progress by accident.
 *
 * The whole design turns on offsets. Prose text nodes are interleaved with UI
 * text nodes: `.unit-strip` puts its 🗑✓💬 buttons INSIDE the paragraph. So
 * offsets are counted over prose only, by one walker used for both storing
 * and restoring -- if those two ever disagree, a highlight reloads onto the
 * wrong words. read-highlighter.e2e.cjs item 7 is built to catch exactly that.
 */
(function () {
  "use strict";

  const REGISTRY = "annotate-read";
  // Text that is chrome, not prose. Counting any of it shifts every offset
  // after it. `.unit-strip` is the one that actually bites -- it sits inside
  // the paragraph it controls.
  const SKIP = ".unit-strip, .unit-chip, .unit-composer, .inline-comments, .code-col, .card-head";

  let highlight = null;

  function supported() {
    return typeof CSS !== "undefined" && !!CSS.highlights && typeof Highlight === "function";
  }
  function rid() {
    return document.body.dataset.responseId || "default";
  }
  function stateKey() { return `annotate.view:${rid()}:highlighter`; }
  function colourKey() { return `annotate.view:${rid()}:highlightcolor`; }

  // One colour for the whole page: picking one repaints every mark rather
  // than only the next drag. That keeps storage as plain [start, end] pairs
  // and keeps the erase rule -- drag over read text to rub it out -- from
  // needing to ask which colour you meant.
  const COLOURS = ["yellow", "green", "orange", "blue", "pink"];
  function colour() {
    let stored = null;
    try { stored = localStorage.getItem(colourKey()); } catch (_) {}
    return COLOURS.indexOf(stored) >= 0 ? stored : COLOURS[0];
  }
  function marksKey(blockId) { return `annotate.read:${rid()}:${blockId}`; }

  function isOn() {
    try { return localStorage.getItem(stateKey()) === "on"; } catch (_) { return false; }
  }

  // ── storage ────────────────────────────────────────────────────────────
  // Per block: { v: <block version>, ranges: [[start, end], ...] }. The
  // version is what makes a stale highlight impossible: once Claude rewrites
  // a block, the text these offsets pointed at is gone, so the entry is
  // dropped rather than reapplied to whatever now occupies those positions.
  function loadMarks(blockId, version) {
    let raw = null;
    try { raw = localStorage.getItem(marksKey(blockId)); } catch (_) { return []; }
    if (!raw) return [];
    let parsed;
    try { parsed = JSON.parse(raw); } catch (_) { return []; }
    if (!parsed || !Array.isArray(parsed.ranges)) return [];
    if (String(parsed.v) !== String(version)) {
      try { localStorage.removeItem(marksKey(blockId)); } catch (_) {}
      return [];
    }
    return parsed.ranges;
  }
  function saveMarks(blockId, version, ranges) {
    try {
      if (!ranges.length) localStorage.removeItem(marksKey(blockId));
      else localStorage.setItem(marksKey(blockId),
        JSON.stringify({ v: String(version), ranges }));
    } catch (_) {}
  }

  // ── the one walker ─────────────────────────────────────────────────────
  function proseWalker(root) {
    return document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (parent && parent.closest(SKIP)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
  }

  // A DOM range → [start, end] character offsets over prose text, or null if
  // either endpoint is not in this root's prose.
  function offsetsOf(root, range) {
    const walk = proseWalker(root);
    let seen = 0, start = null, end = null, node;
    while ((node = walk.nextNode())) {
      const len = node.textContent.length;
      if (node === range.startContainer) start = seen + range.startOffset;
      if (node === range.endContainer) end = seen + range.endOffset;
      seen += len;
    }
    // A range whose endpoints are ELEMENTS rather than text nodes (a
    // select-all inside a paragraph, say) needs the element's own extent.
    if (start === null || end === null) {
      const bounds = elementBounds(root, range);
      if (!bounds) return null;
      if (start === null) start = bounds[0];
      if (end === null) end = bounds[1];
    }
    if (start === null || end === null || end <= start) return null;
    return [start, end];
  }
  function elementBounds(root, range) {
    const walk = proseWalker(root);
    let seen = 0, lo = null, hi = null, node;
    while ((node = walk.nextNode())) {
      const len = node.textContent.length;
      if (range.intersectsNode && range.intersectsNode(node)) {
        if (lo === null) lo = seen;
        hi = seen + len;
      }
      seen += len;
    }
    return lo === null ? null : [lo, hi];
  }

  // [start, end] offsets → a live DOM range, or null if the text moved out
  // from under them (a shorter block after a rewrite, say).
  function rangeFrom(root, start, end) {
    const walk = proseWalker(root);
    let seen = 0, node;
    const range = document.createRange();
    let haveStart = false;
    while ((node = walk.nextNode())) {
      const len = node.textContent.length;
      if (!haveStart && start < seen + len) {
        range.setStart(node, start - seen);
        haveStart = true;
      }
      if (haveStart && end <= seen + len) {
        range.setEnd(node, end - seen);
        return range;
      }
      seen += len;
    }
    return null;
  }

  // ── interval algebra ───────────────────────────────────────────────────
  // Kept sorted and non-overlapping, so "is this stretch already read?" is a
  // coverage question rather than a search through overlapping duplicates.
  function normalise(ranges) {
    const sorted = ranges.slice().sort((a, b) => a[0] - b[0]);
    const out = [];
    for (const [s, e] of sorted) {
      const last = out[out.length - 1];
      if (last && s <= last[1]) last[1] = Math.max(last[1], e);
      else out.push([s, e]);
    }
    return out;
  }
  function covers(ranges, s, e) {
    let at = s;
    for (const [rs, re] of ranges) {
      if (re <= at) continue;
      if (rs > at) return false;
      at = re;
      if (at >= e) return true;
    }
    return at >= e;
  }
  function subtract(ranges, s, e) {
    const out = [];
    for (const [rs, re] of ranges) {
      if (re <= s || rs >= e) { out.push([rs, re]); continue; }
      if (rs < s) out.push([rs, s]);
      if (re > e) out.push([e, re]);
    }
    return out;
  }

  // ── painting ───────────────────────────────────────────────────────────
  function blocks() {
    return [...document.querySelectorAll("main.prose section.block[data-block-id]")];
  }
  function contentOf(section) {
    return section.querySelector(".block-content") || section;
  }

  function repaint() {
    if (!supported()) return;
    if (!highlight) {
      highlight = new Highlight();
      CSS.highlights.set(REGISTRY, highlight);
    }
    highlight.clear();
    if (!isOn()) return;
    for (const section of blocks()) {
      const root = contentOf(section);
      const stored = loadMarks(section.dataset.blockId, section.dataset.version);
      for (const [s, e] of stored) {
        const range = rangeFrom(root, s, e);
        if (range) highlight.add(range);
      }
    }
  }

  // ── recording ──────────────────────────────────────────────────────────
  function onMouseUp(ev) {
    if (!isOn() || !supported()) return;
    // A click on a control is not a reading gesture. Without this, clicking
    // the toggle (or any button) while a stretch is still selected re-runs
    // the recording on that live selection -- and because the stretch is
    // already highlighted, that takes the ERASE branch and silently rubs out
    // the highlight just made. Found by e2e item 9; item 10 pins it.
    // Deliberately not "must be inside main.prose": a drag released in the
    // page margin is still a reading gesture and should count.
    const t = ev && ev.target;
    if (t && t.closest && t.closest("button, a, input, textarea, .page-header, footer")) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);

    // Both endpoints must sit in ONE block's prose. A drag that runs off the
    // end of a card would otherwise be recorded against whichever block
    // happened to own the start.
    const section = range.startContainer.parentElement
      && range.startContainer.parentElement.closest("section.block[data-block-id]");
    if (!section) return;
    const endSection = range.endContainer.parentElement
      && range.endContainer.parentElement.closest("section.block[data-block-id]");
    if (endSection !== section) return;
    // Panes keep their own light palette; a marker on top of syntax colours
    // fights both, and the anchor row already carries a wash.
    if (range.startContainer.parentElement.closest(".code-col")) return;

    const root = contentOf(section);
    const span = offsetsOf(root, range);
    if (!span) return;
    const [s, e] = span;

    const blockId = section.dataset.blockId;
    const version = section.dataset.version;
    const existing = normalise(loadMarks(blockId, version));
    // Same gesture, both jobs: a drag entirely inside what is already read
    // rubs it out, anything else adds to it.
    const next = covers(existing, s, e)
      ? subtract(existing, s, e)
      : normalise(existing.concat([[s, e]]));
    saveMarks(blockId, version, next);
    repaint();
    // Deliberately NOT collapsing the selection: script.js quotes the live
    // selection into a comment when a hover-action button is clicked, and
    // clearing it here would break that while looking fine.
  }

  function clearAll() {
    for (const section of blocks()) {
      try { localStorage.removeItem(marksKey(section.dataset.blockId)); } catch (_) {}
    }
    repaint();
  }

  function syncControls() {
    const on = isOn();
    document.body.dataset.highlighter = on ? "on" : "off";
    const btn = document.getElementById("highlighter-toggle");
    if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");

    // The colour lives on <body> and every paint rule keys off it, so this
    // one assignment recolours the swatch, the marks and the palette's own
    // pressed state together -- there is no second place to keep in step.
    const c = colour();
    document.body.dataset.highlightColor = c;
    const pop = document.getElementById("palette-pop");
    if (pop) {
      pop.querySelectorAll("[data-color]").forEach((b) => {
        b.setAttribute("aria-pressed", b.dataset.color === c ? "true" : "false");
      });
    }
  }

  function init() {
    const btn = document.getElementById("highlighter-toggle");
    const clear = document.getElementById("highlighter-clear");
    // No API, no feature: the control would be a button that does nothing.
    if (!supported()) {
      if (btn) btn.hidden = true;
      if (clear) clear.hidden = true;
      const swatch = document.getElementById("highlighter-palette");
      if (swatch) swatch.hidden = true;
      return;
    }
    if (btn) {
      btn.addEventListener("click", () => {
        try { localStorage.setItem(stateKey(), isOn() ? "off" : "on"); } catch (_) {}
        syncControls();
        repaint();
      });
    }
    if (clear) clear.addEventListener("click", clearAll);
    const pop = document.getElementById("palette-pop");
    if (pop) {
      pop.querySelectorAll("[data-color]").forEach((b) => {
        b.addEventListener("click", () => {
          try { localStorage.setItem(colourKey(), b.dataset.color); } catch (_) {}
          syncControls();
        });
      });
    }
    document.addEventListener("mouseup", onMouseUp);
    syncControls();
    repaint();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Blocks are rendered and re-rendered by script.js long after this file
  // runs, so the paint has to be re-applied when the document changes.
  // Exposed rather than self-observing: script.js knows when a render is
  // finished, a MutationObserver would only know that it started.
  window.annotateHighlighter = { repaint, clearAll };
})();
