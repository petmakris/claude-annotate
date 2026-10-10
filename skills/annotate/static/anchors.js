// skills/annotate/static/anchors.js
/* Anchors: a selection on the page ⇄ the words it covers.
 *
 * A mark has to survive what the page does to its own DOM: Claude rewrites
 * a block's innerHTML, the glossary wraps terms in spans and unwraps them
 * again, search inserts <mark> and normalises it away. So a mark is never
 * stored as a DOM Range. It is stored as text: the selected words plus up to
 * 32 characters either side, and found again by searching the block's prose
 * for those words and preferring the occurrence whose surroundings match.
 *
 * Prose is counted by ONE walker that skips UI living inside a block's
 * content (the comment box and chips). Storing and finding must agree on
 * that text exactly, or a mark comes back on the wrong words.
 *
 * Marks are painted with the CSS Custom Highlight API, so nothing here ever
 * wraps or splits the page's text nodes either.
 */
(function () {
  "use strict";

  const SKIP = ".sel-chip, .code-col, .block-label, .sp-card";
  const CONTEXT = 32;
  const KINDS = ["delete", "compact", "comment"];

  function supported() {
    return typeof CSS !== "undefined" && !!CSS.highlights && typeof Highlight === "function";
  }
  function contentOf(section) {
    return section ? section.querySelector(".block-content") : null;
  }

  function walker(root) {
    return document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const p = node.parentElement;
        return p && p.closest(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
  }

  function textOf(root) {
    const w = walker(root);
    let out = "", n;
    while ((n = w.nextNode())) out += n.textContent;
    return out;
  }

  // A DOM range → [start, end] over prose text, or null when it does not
  // fall in this root's prose. Element endpoints (a triple-click, a
  // select-all) are resolved to the extent of the text nodes they touch.
  function offsetsOf(root, range) {
    const w = walker(root);
    let seen = 0, start = null, end = null, lo = null, hi = null, n;
    while ((n = w.nextNode())) {
      const len = n.textContent.length;
      if (n === range.startContainer) start = seen + range.startOffset;
      if (n === range.endContainer) end = seen + range.endOffset;
      if (range.intersectsNode(n)) { if (lo === null) lo = seen; hi = seen + len; }
      seen += len;
    }
    if (start === null) start = lo;
    if (end === null) end = hi;
    if (start === null || end === null || end <= start) return null;
    return [start, end];
  }

  function rangeFrom(root, start, end) {
    const w = walker(root);
    const range = document.createRange();
    let seen = 0, haveStart = false, n;
    while ((n = w.nextNode())) {
      const len = n.textContent.length;
      if (!haveStart && start < seen + len) { range.setStart(n, start - seen); haveStart = true; }
      if (haveStart && end <= seen + len) { range.setEnd(n, end - seen); return range; }
      seen += len;
    }
    return null;
  }

  function anchorFor(section, range) {
    const root = contentOf(section);
    if (!root || !section.dataset.blockId) return null;
    const span = offsetsOf(root, range);
    if (!span) return null;
    const text = textOf(root);
    let [s, e] = span;
    while (s < e && /\s/.test(text[s])) s++;
    while (e > s && /\s/.test(text[e - 1])) e--;
    if (e <= s) return null;
    const a = {
      block_id: section.dataset.blockId,
      selected_text: text.slice(s, e),
      prefix: text.slice(Math.max(0, s - CONTEXT), s),
      suffix: text.slice(e, e + CONTEXT),
    };
    const c = range.commonAncestorContainer;
    const el = c.nodeType === 1 ? c : c.parentElement;
    const authored = el && el.closest("[data-annotate-id]");
    if (authored && root.contains(authored)) a.step_id = authored.dataset.annotateId;
    return a;
  }

  function commonTail(a, b) {
    let i = 0;
    while (i < a.length && i < b.length && a[a.length - 1 - i] === b[b.length - 1 - i]) i++;
    return i;
  }
  function commonHead(a, b) {
    let i = 0;
    while (i < a.length && i < b.length && a[i] === b[i]) i++;
    return i;
  }

  // Whitespace never decides whether words match: markdown keeps the source
  // "\n" inside a paragraph and a strip stores its words collapsed. The search
  // runs on a copy with every whitespace run folded to one space, and the
  // answer is mapped back to RAW offsets.
  function fold(s) { return s.replace(/\s+/g, " "); }
  function folded(text) {
    let out = "";
    const from = [], to = [];
    for (let i = 0; i < text.length;) {
      if (/\s/.test(text[i])) {
        let j = i;
        while (j < text.length && /\s/.test(text[j])) j++;
        out += " "; from.push(i); to.push(j); i = j;
      } else { out += text[i]; from.push(i); to.push(i + 1); i++; }
    }
    return { out, from, to };
  }

  // Every occurrence of the words, scored by how much of the stored context
  // still surrounds it; the best wins, the first on a tie. `from`, a raw
  // offset, skips every occurrence that starts before it.
  function locate(section, anchor, from = 0) {
    const root = contentOf(section);
    if (!root) return null;
    return locateText(textOf(root), anchor, from);
  }

  // The same search over prose text already in hand: edit.js finds many
  // anchors in one detached render, and folds its text once, not per anchor.
  //
  // opts.words: only an occurrence that starts and ends on a word boundary
  // ("roll" is not found inside "scroll"). opts.context: only an occurrence
  // some of whose stored surroundings still agree (score above zero) — the
  // words alone, somewhere else, are not the same words.
  const WORD = /[\p{L}\p{N}_]/u;
  let lastText = null, lastFold = null;
  function locateText(raw, anchor, from = 0, opts = {}) {
    if (!anchor || !anchor.selected_text) return null;
    if (raw !== lastText) { lastText = raw; lastFold = folded(raw); }
    const f = lastFold;
    const text = f.out;
    const want = fold(anchor.selected_text), pre = fold(anchor.prefix || ""), suf = fold(anchor.suffix || "");
    const edge = (i) => (!WORD.test(want[0]) || i === 0 || !WORD.test(text[i - 1]))
      && (!WORD.test(want[want.length - 1]) || !WORD.test(text[i + want.length] || ""));
    let best = -1, bestScore = -1, i = -1;
    while (i + 1 < f.from.length && f.from[i + 1] < from) i++;
    while ((i = text.indexOf(want, i + 1)) !== -1) {
      if (opts.words && !edge(i)) continue;
      const score = commonTail(text.slice(Math.max(0, i - pre.length), i), pre)
        + commonHead(text.slice(i + want.length, i + want.length + suf.length), suf);
      if (opts.context && score <= 0) continue;
      if (score > bestScore) { best = i; bestScore = score; }
    }
    return best < 0 ? null : [f.from[best], f.to[best + want.length - 1]];
  }

  function rangeFor(section, anchor) {
    const span = locate(section, anchor);
    return span ? rangeFrom(contentOf(section), span[0], span[1]) : null;
  }

  // The prose offset under a point, or null when the point is not on prose.
  function offsetAt(root, x, y) {
    let node = null, off = 0;
    if (document.caretPositionFromPoint) {
      const p = document.caretPositionFromPoint(x, y);
      if (p) { node = p.offsetNode; off = p.offset; }
    } else if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      if (r) { node = r.startContainer; off = r.startOffset; }
    }
    if (!node || node.nodeType !== 3 || !root.contains(node)) return null;
    const w = walker(root);
    let seen = 0, n;
    while ((n = w.nextNode())) {
      if (n === node) return seen + off;
      seen += n.textContent.length;
    }
    return null;
  }

  function registry(name) {
    let h = CSS.highlights.get(name);
    if (!h) { h = new Highlight(); CSS.highlights.set(name, h); }
    return h;
  }

  function paint(items) {
    if (!supported()) return;
    for (const k of KINDS) registry("annotate-" + k).clear();
    for (const it of items || []) {
      if (KINDS.indexOf(it.kind) < 0) continue;
      const r = rangeFor(it.section, it.anchor);
      if (r) registry("annotate-" + it.kind).add(r);
    }
  }

  // One range lit under `name`: the whole-block selection's scope by
  // default, and read-aloud's page sentence as "annotate-speaking".
  function setScope(range, name = "annotate-scope") {
    if (!supported()) return;
    const h = registry(name);
    h.clear();
    if (range) h.add(range);
  }

  window.AnnotateAnchors = {
    SKIP, supported, contentOf, textOf, offsetsOf, rangeFrom, anchorFor,
    locate, locateText, rangeFor, offsetAt, paint, setScope, CONTEXT,
  };
})();
