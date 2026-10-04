// annotate's rich section editor: the rendered section, editable in place
// (ProseMirror), saving only what changed.
//
//   AnnotateRich.formatOf(text)          -> "html" | "md"
//   AnnotateRich.canShow(text, format)   -> null | reason
//   AnnotateRich.mount(host, {text, format, onChange, onSave, onDone, paintCode}) -> handle
//
// paintCode(text, lang) -> HTML | null, optional: the page's highlighter. A
// code block then looks as the page paints it (`code.sk-fence`, one
// `span.sk` per token), redrawn as it is typed in. Display only: the
// document and what is saved never see it.
//
// The handle: getText() (the minimal-change save, see save.js), stats(),
// focusAt(offset), setText(text), focus(), isFocused(), destroy(), linkAt(),
// holdSelection(on),
// setLink(href | null), onLinkRequest (set by the caller, called on ⌘K with
// the handle), and view (the EditorView, for tests).
//
// onChange() is called with no argument after every change to the
// document; getText() gives the text, and caches it per document.
import { EditorState, Plugin, PluginKey, TextSelection } from "prosemirror-state";
import { EditorView, Decoration, DecorationSet } from "prosemirror-view";
import { schema } from "./schema.js";
import { chunksFor, bulletOf, formatOf, md } from "./parse.js";
import { minimalSave, eolOf } from "./save.js";
import { keys } from "./keys.js";
import { cleanPastedHtml, stripSlice } from "./paste.js";

const S = schema.nodes, M = schema.marks;
const noop = () => {};

export { formatOf };
export const pm = { TextSelection };

const MERGED = "this section has a table with merged cells";
const UNREADABLE = "this section couldn't be read as blocks";
const UNSHOWN = "this section has content Rich editing can't show";

// Every element the schema reads as itself. Anything else (<details>'s
// <summary>, <dl>, <svg>, <iframe>, <figcaption>, …) would be dropped or
// flattened into plain words by the parse, and a save would lose it.
const HELD = new Set(("p h1 h2 h3 h4 h5 h6 blockquote div section article aside header footer nav hr pre code "
  + "ul ol li table thead tbody tr td th img br a strong b em i "
  + "span u s del ins sub sup kbd mark small abbr q cite var samp time font").split(" "));
function holdsUnshown(text, fmt) {
  const t = document.createElement("template");
  t.innerHTML = fmt === "html" ? text : md().render(text);
  for (const el of t.content.querySelectorAll("*")) {
    const tag = el.tagName.toLowerCase();
    if (!HELD.has(tag)) return true;
    if ((tag === "a" && !el.hasAttribute("href")) || (tag === "img" && !el.hasAttribute("src"))) return true;
  }
  return false;
}

function load(text, fmt) {
  const parsed = chunksFor(text, fmt);
  const nodes = parsed.chunks.flatMap((c) => c.nodes);
  const doc = S.doc.createChecked(null, nodes.length ? nodes : [S.paragraph.create()]);
  return { parsed, doc };
}

// A table cell in the editor holds words, not blocks: a cell with a list
// or paragraphs in it would be torn out of its table.
const CELL_BLOCKS = "p, div, ul, ol, li, h1, h2, h3, h4, h5, h6, blockquote, pre, table, hr, section, article, details, figure";
function cellsHoldBlocks(text, fmt) {
  const t = document.createElement("template");
  t.innerHTML = fmt === "html" ? text : md().render(text);
  return [...t.content.querySelectorAll("td, th")].some((c) => c.querySelector(CELL_BLOCKS));
}

export function canShow(text, format) {
  const fmt = format === "html" ? "html" : "md";
  let doc;
  try {
    doc = load(text, fmt).doc;
    if (holdsUnshown(text, fmt)) return UNSHOWN;
    if (cellsHoldBlocks(text, fmt)) return UNREADABLE;
  } catch (_) { return UNREADABLE; }
  let merged = false;
  doc.descendants((n) => {
    if (merged) return false;
    if ((n.type === S.table_cell || n.type === S.table_header) && (n.attrs.colspan > 1 || n.attrs.rowspan > 1)) merged = true;
    return !merged;
  });
  return merged ? MERGED : null;
}

// An id is the block's own: Enter on an <li data-annotate-id> splits it,
// and the new half must not carry the same id. Only an id that a change
// duplicated is dropped; one the stored text already repeats is left alone.
function idsOf(doc) {
  const n = new Map();
  doc.descendants((node) => {
    const ex = node.attrs && node.attrs.extra;
    if (!ex || !ex.length) return;
    for (const [k, v] of ex) if (k === "data-annotate-id" || k === "id") { const key = k + "=" + v; n.set(key, (n.get(key) || 0) + 1); }
  });
  return n;
}
const uniqueIds = new Plugin({
  appendTransaction(trs, old, state) {
    if (!trs.some((t) => t.docChanged)) return null;
    const before = idsOf(old.doc);
    const seen = new Map();
    let tr = null;
    state.doc.descendants((n, pos) => {
      const ex = n.attrs && n.attrs.extra;
      if (!ex || !ex.length) return;
      const drop = ex.filter(([k, v]) => {
        if (k !== "data-annotate-id" && k !== "id") return false;
        const key = k + "=" + v, c = (seen.get(key) || 0) + 1;
        seen.set(key, c);
        return c > Math.max(1, before.get(key) || 0);
      }).map(([k]) => k);
      if (!drop.length) return;
      tr = tr || state.tr;
      tr.setNodeMarkup(pos, null, Object.assign({}, n.attrs, { extra: ex.filter(([k]) => !drop.includes(k)) }));
    });
    return tr;
  },
});

// Text of the page's rendering of `text`, as AnnotateAnchors counts it.
function renderedText(text) {
  const c = document.createElement("div");
  c.className = "block-content";
  const page = window.AnnotatePage && window.AnnotatePage.renderMarkdown;
  c.innerHTML = page ? page(text) : md().render(text);
  if (window.AnnotateAnchors && window.AnnotateAnchors.textOf) return window.AnnotateAnchors.textOf(c);
  const w = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
  let out = "", n;
  while ((n = w.nextNode())) out += n.textContent;
  return out;
}

// The document position of character `offset` of the rendered text. The
// rendering and the document hold the same words; they differ in the
// whitespace between and inside blocks (newlines between rendered blocks,
// soft breaks the editor shows as spaces), so the two are walked together,
// skipping whitespace on whichever side has it extra.
function posAtRendered(doc, rendered, offset) {
  const chars = [], at = [];
  doc.descendants((n, pos) => {
    if (n.isText) { for (let k = 0; k < n.text.length; k++) { chars.push(n.text[k]); at.push(pos + k); } }
    else if (n.type === S.hard_break) { chars.push("\n"); at.push(pos); }
  });
  let i = 0, j = 0;
  while (i < offset && j < chars.length) {
    if (rendered[i] === chars[j]) { i++; j++; }
    else if (/\s/.test(rendered[i])) i++;
    else if (/\s/.test(chars[j])) j++;
    else i++;
  }
  while (j < chars.length && /\s/.test(chars[j]) && !/\s/.test(rendered[i] || "")) j++;
  if (j < chars.length) return at[j];
  return chars.length ? at[chars.length - 1] + 1 : null;
}

// The link around the selection: the whole run of text carrying the same
// link mark, or null.
function linkRange(state) {
  const { $from, from, to, empty } = state.selection;
  let mark = null;
  for (const n of [$from.nodeAfter, $from.nodeBefore]) {
    if (!mark && n) mark = M.link.isInSet(n.marks);
  }
  if (!mark && !empty) {
    state.doc.nodesBetween(from, to, (n) => { if (!mark && n.isText) mark = M.link.isInSet(n.marks); return !mark; });
  }
  if (!mark) return null;
  const parent = $from.parent, start = $from.start();
  let idx = $from.index();
  if (idx >= parent.childCount || !mark.isInSet(parent.child(idx).marks)) idx = Math.max(0, idx - 1);
  if (!mark.isInSet(parent.child(idx).marks)) return null;
  let a = idx, b = idx;
  while (a > 0 && mark.isInSet(parent.child(a - 1).marks)) a--;
  while (b < parent.childCount - 1 && mark.isInSet(parent.child(b + 1).marks)) b++;
  let off = 0;
  for (let k = 0; k < a; k++) off += parent.child(k).nodeSize;
  let end = off;
  for (let k = a; k <= b; k++) end += parent.child(k).nodeSize;
  return { from: start + off, to: start + end, mark };
}

// What only the screen sees, never the document. A tight list's items
// hold paragraphs in the model but none on the page, so the list is marked
// for the stylesheet. With `paint`, a code block's tokens get the page's
// colours: paint() returns `<span class="sk" style>` runs whose text, in
// order, is the code's; and the fence's final newline is hidden, as the
// page hides it.
function display(paint) {
  const cache = new Map();
  const tokens = (text, lang) => {
    const key = lang + "\u0000" + text;
    if (cache.has(key)) return cache.get(key);
    let out = null;
    try {
      const html = paint(text, lang);
      if (html) {
        const t = document.createElement("template");
        t.innerHTML = html;
        out = [];
        let off = 0;
        for (const n of t.content.childNodes) {
          const len = n.textContent.length;
          if (n.nodeType === 1 && len) out.push([off, off + len, n.getAttribute("style") || ""]);
          off += len;
        }
        if (off !== text.length) out = null;
      }
    } catch (_) { out = null; }
    if (cache.size > 200) cache.clear();
    cache.set(key, out);
    return out;
  };
  const build = (doc) => {
    const decos = [];
    doc.descendants((n, pos) => {
      if ((n.type === S.bullet_list || n.type === S.ordered_list) && n.attrs.tight) {
        decos.push(Decoration.node(pos, pos + n.nodeSize, { class: "ed-tight" }));
      } else if (paint && n.type === S.code_block) {
        const text = n.textContent;
        for (const [a, b, style] of tokens(text, n.attrs.params) || []) {
          decos.push(Decoration.inline(pos + 1 + a, pos + 1 + b, { class: "sk", style }));
        }
        // A fence's text ends in the newline before its closing ```, which
        // the page does not show as a line of its own.
        if (text.endsWith("\n")) {
          decos.push(Decoration.inline(pos + text.length, pos + 1 + text.length, { class: "ed-fence-eol" }));
        }
        return false;
      }
      return true;
    });
    return DecorationSet.create(doc, decos);
  };
  return new Plugin({
    state: { init: (_, state) => build(state.doc), apply: (tr, old) => (tr.docChanged ? build(tr.doc) : old) },
    props: { decorations(state) { return this.getState(state); } },
  });
}

// The selection, kept visible while focus is elsewhere (the bar's link
// field): a mark on the range, moved through any change, until released.
const heldKey = new PluginKey("held");
const held = new Plugin({
  key: heldKey,
  state: {
    init: () => DecorationSet.empty,
    apply(tr, set) {
      const m = tr.getMeta(heldKey);
      if (m === null) return DecorationSet.empty;
      if (m) return DecorationSet.create(tr.doc, [Decoration.inline(m.from, m.to, { class: "ed-sel-held" })]);
      return set.map(tr.mapping, tr.doc);
    },
  },
  props: { decorations(state) { return heldKey.getState(state); } },
});

// The page's <pre><code class="sk-fence language-x">, for the stylesheet's
// fence rules; the schema's own toDOM (what an HTML save writes) is left alone.
function fenceView(node) {
  const pre = document.createElement("pre");
  const code = document.createElement("code");
  const cls = (n) => "sk-fence" + (n.attrs.params ? " language-" + n.attrs.params.replace(/[^\w-]/g, "") : "");
  code.className = cls(node);
  pre.appendChild(code);
  return {
    dom: pre, contentDOM: code,
    update(n) { if (n.type !== node.type) return false; node = n; code.className = cls(n); return true; },
  };
}

export function mount(host, opts) {
  const fmt = opts.format === "html" ? "html" : "md";
  const onChange = opts.onChange || noop;
  let base, parsed, bullet, eol;
  const handle = {};
  const plugins = [
    ...keys({
      onSave: () => (opts.onSave || noop)(),
      onDone: () => (opts.onDone || noop)(),
      onLink: () => { if (handle.onLinkRequest) handle.onLinkRequest(handle); },
    }),
    uniqueIds,
    display(typeof opts.paintCode === "function" ? opts.paintCode : null),
    held,
  ];
  const stateFor = (text) => {
    const r = load(text, fmt);
    base = text;
    parsed = r.parsed;
    bullet = fmt === "md" ? bulletOf(text) : "-";
    eol = eolOf(text);
    return EditorState.create({ doc: r.doc, plugins });
  };

  const el = document.createElement("div");
  el.className = "block-content ed-rich";
  host.appendChild(el);
  let cache = null;
  const view = new EditorView(el, {
    state: stateFor(opts.text || ""),
    // pre-wrap is what ProseMirror needs, and without it Chromium types a
    // space next to a mark or a selection edge as U+00A0: a byte the reader
    // never typed. Set here so it never depends on the page's stylesheet.
    attributes: { role: "textbox", "aria-multiline": "true", spellcheck: "true", class: "ed-rich-pm",
      style: "white-space: pre-wrap; word-wrap: break-word; outline: none" },
    nodeViews: typeof opts.paintCode === "function" ? { code_block: fenceView } : {},
    transformPastedHTML: cleanPastedHtml,
    transformPasted: stripSlice,
    dispatchTransaction(tr) {
      view.updateState(view.state.apply(tr));
      if (tr.docChanged) { cache = null; onChange(); }
    },
  });
  const save = () => {
    if (cache && cache.doc === view.state.doc) return cache;
    const r = minimalSave(base, parsed.chunks, view.state.doc, fmt, { bullet, eol, refs: parsed.refs });
    cache = { doc: view.state.doc, text: r.text, stats: r.stats };
    return cache;
  };

  Object.assign(handle, {
    view,
    getText: () => save().text,
    stats: () => save().stats,
    focus: () => view.focus(),
    isFocused: () => view.hasFocus(),
    setText(text) {
      view.updateState(stateFor(text));
      cache = null;
      onChange();
    },
    focusAt(offset) {
      const doc = view.state.doc;
      let pos = null;
      if (offset >= 0) {
        const r = renderedText(base);
        if (offset <= r.length) pos = posAtRendered(doc, r, offset);
      }
      const sel = pos === null ? TextSelection.atStart(doc) : TextSelection.near(doc.resolve(pos));
      view.dispatch(view.state.tr.setSelection(sel).scrollIntoView());
      view.focus();
    },
    linkAt() {
      const r = linkRange(view.state);
      return r ? { from: r.from, to: r.to, href: r.mark.attrs.href } : null;
    },
    setLink(href) {
      const state = view.state, r = linkRange(state);
      const { from, to, empty } = state.selection;
      let tr = null;
      if (r) {
        tr = state.tr.removeMark(r.from, r.to, M.link);
        if (href) tr.addMark(r.from, r.to, M.link.create(Object.assign({}, r.mark.attrs, { href })));
      } else if (href && !empty) {
        tr = state.tr.addMark(from, to, M.link.create({ href }));
      } else if (href) {
        tr = state.tr.insert(from, schema.text(href, [M.link.create({ href })]));
      }
      if (tr) view.dispatch(tr.scrollIntoView());
      view.focus();
    },
    // Keep the selection visibly marked (true) or stop (false).
    holdSelection(on) {
      const { from, to } = view.state.selection;
      view.dispatch(view.state.tr.setMeta(heldKey, on && from < to ? { from, to } : null));
    },
    destroy() { view.destroy(); el.remove(); },
  });
  return handle;
}
