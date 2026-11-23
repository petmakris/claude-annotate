// Writing nodes back out, as HTML (HTML sections, and blocks that
// came from raw HTML inside markdown) or as markdown.
import { DOMSerializer } from "prosemirror-model";
import { MarkdownSerializer, defaultMarkdownSerializer } from "prosemirror-markdown";
import { schema } from "./schema.js";

// ProseMirror's serializer writes `style` through style.cssText, which
// rewrites it (`color:red` comes out `color: red;`). For the stored text the
// attribute is carried under another name, in the same place, and renamed
// back in the HTML string, so it is written exactly as it was stored.
const RAW = "data-rich-raw-style";
function rawStyle(spec) {
  if (!Array.isArray(spec)) return spec;
  return spec.map((part, k) => {
    if (k === 0) return part;
    if (Array.isArray(part)) return rawStyle(part);
    if (k === 1 && part && typeof part === "object" && part.nodeType === undefined && "style" in part) {
      const o = {};
      for (const key of Object.keys(part)) o[key === "style" ? RAW : key] = part[key];
      return o;
    }
    return part;
  });
}
const wrapAll = (fns) => Object.fromEntries(Object.entries(fns).map(([k, f]) => [k, (...a) => rawStyle(f(...a))]));
const base = DOMSerializer.fromSchema(schema);
const domSer = new DOMSerializer(wrapAll(base.nodes), wrapAll(base.marks));

// ── HTML ─────────────────────────────────────────────────────────────────
// The editor needs a <p> inside every <li>; the stored text has
// `<li>words</li>`. A sole attribute-less <p> in an <li> is unwrapped.
function tidy(root) {
  for (const li of root.querySelectorAll("li")) {
    const ps = [...li.children].filter((c) => c.tagName === "P");
    if (ps.length === 1 && li.firstElementChild === ps[0] && !ps[0].attributes.length) ps[0].replaceWith(...ps[0].childNodes);
  }
  return root;
}

export function nodeToHtml(node) {
  const box = document.createElement("div");
  box.appendChild(domSer.serializeNode(node));
  return tidy(box).innerHTML.split(" " + RAW + "=").join(" style=");
}

// ── markdown ─────────────────────────────────────────────────────────────
// A node with anything markdown cannot say (extra attributes, inline
// elements kept as they are) is written as an HTML block instead.
export function needsHtml(node) {
  let need = false;
  const check = (n) => {
    if (need) return false;
    if (n.attrs && Array.isArray(n.attrs.extra) && n.attrs.extra.length) need = true;
    if (n.attrs && Array.isArray(n.attrs.codeExtra) && n.attrs.codeExtra.length) need = true;
    for (const m of n.marks) if (m.type.name === "span" || (m.attrs.extra && m.attrs.extra.length) || (m.attrs.tag && m.attrs.tag !== m.type.name)) need = true;
    if (n.type.name === "table_cell" || n.type.name === "table_header") {
      if (n.attrs.colspan !== 1 || n.attrs.rowspan !== 1) need = true;
    }
    if (n.type.name === "container") need = true;
    return !need;
  };
  check(node);
  node.descendants(check);
  return need;
}

const d = defaultMarkdownSerializer;
function cellText(state, cell) {
  // Inline content on one line, pipes escaped. A line break in a cell is
  // <br>: markdown's own break (a backslash before a newline) cannot sit
  // inside a table row.
  const sub = new MarkdownSerializer(Object.assign({}, mdNodes, { hard_break(st) { st.write("<br>"); } }), mdMarks);
  const p = schema.nodes.paragraph.create(null, cell.content);
  return sub.serialize(schema.nodes.doc.create(null, p)).replace(/\n/g, " ").replace(/\|/g, "\\|");
}
const mdNodes = Object.assign({}, d.nodes, {
  bullet_list(state, node) {
    state.renderList(node, "  ", () => (state.options.bullet || "-") + " ");
  },
  table(state, node) {
    const rows = [];
    node.forEach((row) => { const r = []; row.forEach((c) => r.push(cellText(state, c))); rows.push(r); });
    const head = rows[0] || [];
    const aligns = [];
    node.firstChild.forEach((c) => aligns.push(c.attrs.align));
    const sep = head.map((_, i) => ({ left: ":---", right: "---:", center: ":---:" }[aligns[i]] || "---"));
    const line = (r) => "| " + r.join(" | ") + " |";
    const out = [line(head), "|" + sep.join("|") + "|", ...rows.slice(1).map(line)];
    state.write(out.join("\n"));
    state.closeBlock(node);
  },
  container(state, node) { state.write(nodeToHtml(node)); state.closeBlock(node); },
  table_row() {}, table_cell() {}, table_header() {},
});
const mdMarks = Object.assign({}, d.marks, {
  span: { open: (s, m) => "<" + m.attrs.tag + ">", close: (s, m) => "</" + m.attrs.tag + ">", escape: false },
});
export const mdSer = new MarkdownSerializer(mdNodes, mdMarks);

export function nodeToMarkdown(node, opts) {
  if (needsHtml(node)) return nodeToHtml(node);
  const doc = schema.nodes.doc.create(null, node);
  const out = mdSer.serialize(doc, { bullet: (opts && opts.bullet) || "-" });
  return out.replace(/\n+$/, "");
}
