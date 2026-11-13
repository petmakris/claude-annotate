// Paste: pasted HTML keeps its structure and the marks the schema has, and
// loses everything else: spans, fonts, styles, classes, ids, data-*.
import { Fragment, Slice } from "prosemirror-model";
import { schema } from "./schema.js";

const M = schema.marks;

const unwrap = (el) => el.replaceWith(...el.childNodes);
const SAFE_HREF = /^(?:https?:|mailto:)/i;
const BLOCKISH = "p, div, ul, ol, li, h1, h2, h3, h4, h5, h6, blockquote, pre, table, section, article";

// What a page's own markup means, read while its classes and styles are
// still there; every rewrite here turns it into the schema's structure.
function readForeign(root) {
  // Google Docs wraps a whole paste in <b style="font-weight:normal"
  // id="docs-internal-guid-…">; bold that says it is not bold is a wrapper.
  for (const b of [...root.querySelectorAll("b, strong")]) {
    const st = (b.getAttribute("style") || "").toLowerCase();
    if (/font-weight:\s*(normal|[1-4]00)\b/.test(st) || (b.id || "").startsWith("docs-internal-guid")) unwrap(b);
  }
  root.querySelectorAll("colgroup, col, .aui-icon").forEach((el) => el.remove());
  // Confluence's code macro: a <pre> whose language is in its params.
  for (const pre of [...root.querySelectorAll("pre")]) {
    if (pre.querySelector("code")) continue;
    const m = /brush:\s*([\w+#-]+)/.exec(pre.getAttribute("data-syntaxhighlighter-params") || "");
    const code = document.createElement("code");
    if (m) code.className = "language-" + m[1];
    code.textContent = pre.textContent;
    pre.replaceChildren(code);
  }
  // Confluence's panels (note, info, warning, tip): a quote.
  for (const panel of [...root.querySelectorAll(".confluence-information-macro, [data-macro-name=note], [data-macro-name=info], [data-macro-name=warning], [data-macro-name=tip], [data-macro-name=panel]")]) {
    if (!root.contains(panel)) continue;
    const q = document.createElement("blockquote");
    // Its title, if it has one, is the quote's first line, in bold.
    const title = panel.querySelector(":scope > .title, :scope > .panelHeader");
    if (title && title.textContent.trim()) {
      const p = document.createElement("p"), b = document.createElement("strong");
      b.textContent = title.textContent.trim();
      p.append(b);
      q.append(p);
    }
    const body = panel.querySelector(".confluence-information-macro-body, .panelContent") || panel;
    q.append(...body.childNodes);
    panel.replaceWith(q);
  }
  // A table inside a cell becomes its cells' words, one per line.
  for (const t of [...root.querySelectorAll("table")].reverse()) {
    if (!t.parentElement || !t.parentElement.closest("td, th")) continue;
    const parts = [];
    for (const c of t.querySelectorAll("td, th")) {
      if (parts.length) parts.push(document.createElement("br"));
      parts.push(...c.childNodes);
    }
    t.replaceWith(...parts);
  }
  // A cell holds words, not blocks: paragraphs and list items inside one
  // become lines, joined by <br>.
  for (const cell of [...root.querySelectorAll("td, th")]) {
    // The source's indentation between blocks is not a space in the words.
    for (const el of cell.querySelectorAll(BLOCKISH)) {
      for (const n of [el.previousSibling, el.nextSibling]) if (n && n.nodeType === 3 && !n.textContent.trim()) n.remove();
    }
    for (const el of [...cell.querySelectorAll(BLOCKISH)].reverse()) {
      let prev = el.previousSibling;
      while (prev && prev.nodeType === 3 && !prev.textContent.trim()) prev = prev.previousSibling;
      if (prev && prev.nodeName !== "BR") el.before(document.createElement("br"));
      unwrap(el);
    }
    const edge = (n) => n && (n.nodeName === "BR" || (n.nodeType === 3 && !n.textContent.trim()));
    while (edge(cell.firstChild)) cell.firstChild.remove();
    while (edge(cell.lastChild)) cell.lastChild.remove();
  }
  // Wrappers: their children are the content.
  for (const el of [...root.querySelectorAll("div, section, article, aside, header, footer, figure, nav, main")].reverse()) unwrap(el);
}

export function cleanPastedHtml(html) {
  const t = document.createElement("template");
  t.innerHTML = html;
  const root = t.content;
  readForeign(root);
  for (const el of [...root.querySelectorAll("*")]) {
    const tag = el.tagName.toLowerCase();
    // Nothing pasted reaches out: no images (a data: URI is a file), no
    // frames or scripts.
    if (["script", "style", "meta", "link", "title", "head", "img", "picture", "iframe", "object", "embed", "svg"].includes(tag)) { el.remove(); continue; }
    // Styles that mean bold / italic / code become the elements.
    const st = (el.getAttribute("style") || "").toLowerCase();
    if (tag === "span" || tag === "font") {
      let inner = [...el.childNodes];
      const wrap = (name) => { const w = document.createElement(name); w.append(...inner); inner = [w]; };
      if (/font-weight:\s*(bold|[6-9]00)/.test(st)) wrap("strong");
      if (/font-style:\s*italic/.test(st)) wrap("em");
      if (/font-family:[^;]*mono/.test(st)) wrap("code");
      el.replaceWith(...inner);
      continue;
    }
    for (const a of [...el.attributes]) {
      // A link only to the web or to mail; cells never merged (Rich
      // cannot show a merged cell, and would refuse the whole section).
      const keep = (tag === "a" && a.name === "href" && SAFE_HREF.test(a.value.trim()))
        || (tag === "ol" && a.name === "start") || (tag === "code" && a.name === "class" && /^language-[\w+#.-]+$/.test(a.value));
      if (!keep) el.removeAttribute(a.name);
    }
  }
  const box = document.createElement("div");
  box.appendChild(root);
  return box.innerHTML;
}

// And whatever reached the slice anyway (a paste from inside the editor
// carries the page's own attributes): no span marks, no extra attributes.
export function stripSlice(slice) {
  const walk = (frag) => {
    const out = [];
    frag.forEach((n) => {
      // <b>/<i> become <strong>/<em>, the page's own words for them.
      if (n.type === schema.nodes.image) return;
      const marks = n.marks.filter((m) => m.type !== M.span
        && !(m.type === M.link && !SAFE_HREF.test(String(m.attrs.href || "").trim()))).map((m) => {
        const a = Object.assign({}, m.attrs);
        if (a.extra) a.extra = [];
        if (m.type === M.strong || m.type === M.em) a.tag = m.type.name;
        return m.type.create(a);
      });
      if (n.isText) { out.push(schema.text(n.text, marks)); return; }
      const attrs = n.attrs.extra ? Object.assign({}, n.attrs, { extra: [] }) : Object.assign({}, n.attrs);
      if (attrs.codeExtra) attrs.codeExtra = [];
      if ("colspan" in attrs) { attrs.colspan = 1; attrs.rowspan = 1; attrs.colwidth = null; }
      out.push(n.type.create(attrs, walk(n.content), marks));
    });
    return Fragment.from(out);
  };
  return new Slice(walk(slice.content), slice.openStart, slice.openEnd);
}
