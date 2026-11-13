// The schema the rich editor edits.
//
// Every node and mark carries `extra`: the element's attributes the schema
// does not model (data-annotate-id, style, class, …), as an ordered list of
// [name, value], so parse → serialise gives them back in the same order.
import { Schema } from "prosemirror-model";

// Attributes that are modelled elsewhere, per tag.
const MODELLED = {
  a: ["href", "title"],
  img: ["src", "alt", "title"],
  ol: ["start"],
  code: [],
  td: ["colspan", "rowspan"],
  th: ["colspan", "rowspan"],
};

export function extraOf(dom, skip) {
  const tag = dom.nodeName.toLowerCase();
  const own = new Set([...(MODELLED[tag] || []), ...(skip || [])]);
  const out = [];
  for (const a of dom.attributes) if (!own.has(a.name)) out.push([a.name, a.value]);
  return out;
}

export function attrsOut(extra, more) {
  const o = {};
  if (more) for (const k in more) if (more[k] != null) o[k] = more[k];
  for (const [k, v] of extra || []) o[k] = v;
  return o;
}

const EX = { extra: { default: [] } };
const block = (tag, spec = {}) => Object.assign({
  attrs: Object.assign({}, EX),
  parseDOM: [{ tag, getAttrs: (d) => ({ extra: extraOf(d) }) }],
  toDOM: (n) => [tag, attrsOut(n.attrs.extra), 0],
}, spec);

// A table cell's `style="text-align:x"` (what markdown-it writes for an
// aligned column) is its alignment, not an extra attribute.
function cellAttrs(d) {
  let extra = extraOf(d);
  let align = null;
  const st = extra.find(([k]) => k === "style");
  const m = st && /^\s*text-align:\s*(left|right|center);?\s*$/.exec(st[1]);
  if (m) { align = m[1]; extra = extra.filter(([k]) => k !== "style"); }
  return {
    extra, align,
    colspan: Number(d.getAttribute("colspan") || 1),
    rowspan: Number(d.getAttribute("rowspan") || 1),
  };
}
function cellOut(n) {
  const more = {};
  if (n.attrs.colspan !== 1) more.colspan = n.attrs.colspan;
  if (n.attrs.rowspan !== 1) more.rowspan = n.attrs.rowspan;
  if (n.attrs.align) more.style = `text-align:${n.attrs.align}`;
  return attrsOut(n.attrs.extra, more);
}
const cellSpec = (tag, role) => ({
  content: "inline*",
  attrs: { extra: { default: [] }, align: { default: null }, colspan: { default: 1 }, rowspan: { default: 1 }, colwidth: { default: null } },
  tableRole: role,
  isolating: true,
  parseDOM: [{ tag, getAttrs: cellAttrs }],
  toDOM: (n) => [tag, cellOut(n), 0],
});

// Inline elements kept as they are (only by the stored text: a paste drops
// them, see paste.js).
const SPAN_TAGS = ["span", "u", "s", "del", "ins", "sub", "sup", "kbd", "mark", "small", "abbr", "q", "cite", "var", "samp", "time", "font"];

export const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: block("p", { content: "inline*", group: "block" }),
    heading: {
      content: "inline*", group: "block", defining: true,
      attrs: { level: { default: 1 }, extra: { default: [] } },
      parseDOM: [1, 2, 3, 4, 5, 6].map((l) => ({ tag: "h" + l, getAttrs: (d) => ({ level: l, extra: extraOf(d) }) })),
      toDOM: (n) => ["h" + n.attrs.level, attrsOut(n.attrs.extra), 0],
    },
    blockquote: block("blockquote", { content: "block+", group: "block", defining: true }),
    // A <div>/<section>/… around blocks: kept as itself.
    container: {
      content: "block+", group: "block", defining: true,
      attrs: { tag: { default: "div" }, extra: { default: [] } },
      parseDOM: ["div", "section", "article", "aside", "header", "footer", "figure", "details", "nav"].map((t) => ({
        tag: t, getAttrs: (d) => ({ tag: t, extra: extraOf(d) }),
      })),
      toDOM: (n) => [n.attrs.tag, attrsOut(n.attrs.extra), 0],
    },
    horizontal_rule: {
      group: "block", attrs: Object.assign({ markup: { default: "---" } }, EX),
      parseDOM: [{ tag: "hr", getAttrs: (d) => ({ extra: extraOf(d) }) }],
      toDOM: (n) => ["hr", attrsOut(n.attrs.extra)],
    },
    code_block: {
      content: "text*", group: "block", code: true, defining: true, marks: "",
      attrs: { params: { default: "" }, extra: { default: [] }, codeExtra: { default: [] } },
      parseDOM: [{
        tag: "pre", preserveWhitespace: "full",
        getAttrs: (d) => {
          const c = d.querySelector(":scope > code");
          let params = "", codeExtra = [];
          if (c) {
            codeExtra = extraOf(c);
            const cls = codeExtra.find(([k]) => k === "class");
            const m = cls && /^(?:sk-fence\s*)?language-([\w+#.-]+)$/.exec(cls[1].trim());
            if (m) { params = m[1]; codeExtra = codeExtra.filter(([k]) => k !== "class"); }
          }
          return { params, extra: extraOf(d), codeExtra };
        },
      }],
      toDOM: (n) => ["pre", attrsOut(n.attrs.extra),
        ["code", attrsOut(n.attrs.codeExtra, n.attrs.params ? { class: "language-" + n.attrs.params } : null), 0]],
    },
    bullet_list: {
      content: "list_item+", group: "block",
      attrs: { tight: { default: true }, bullet: { default: "-" }, extra: { default: [] } },
      parseDOM: [{ tag: "ul", getAttrs: (d) => ({ tight: !d.querySelector(":scope > li > p"), extra: extraOf(d) }) }],
      toDOM: (n) => ["ul", attrsOut(n.attrs.extra), 0],
    },
    ordered_list: {
      content: "list_item+", group: "block",
      attrs: { order: { default: 1 }, tight: { default: true }, extra: { default: [] } },
      parseDOM: [{ tag: "ol", getAttrs: (d) => ({
        order: d.hasAttribute("start") ? +d.getAttribute("start") : 1,
        tight: !d.querySelector(":scope > li > p"), extra: extraOf(d),
      }) }],
      toDOM: (n) => ["ol", attrsOut(n.attrs.extra, n.attrs.order !== 1 ? { start: n.attrs.order } : null), 0],
    },
    list_item: block("li", { content: "paragraph block*", defining: true }),
    table: {
      content: "table_row+", group: "block", tableRole: "table", isolating: true,
      attrs: { extra: { default: [] }, head: { default: false } },
      parseDOM: [{ tag: "table", getAttrs: (d) => ({ extra: extraOf(d), head: !!d.querySelector(":scope > thead") }) }],
      toDOM: (n) => ["table", attrsOut(n.attrs.extra), ["tbody", 0]],
    },
    table_row: {
      content: "(table_cell | table_header)*", tableRole: "row",
      attrs: { extra: { default: [] } },
      parseDOM: [{ tag: "tr", getAttrs: (d) => ({ extra: extraOf(d) }) }],
      toDOM: (n) => ["tr", attrsOut(n.attrs.extra), 0],
    },
    table_cell: cellSpec("td", "cell"),
    table_header: cellSpec("th", "header_cell"),
    text: { group: "inline" },
    image: {
      inline: true, group: "inline", draggable: true,
      attrs: { src: {}, alt: { default: null }, title: { default: null }, extra: { default: [] } },
      parseDOM: [{ tag: "img[src]", getAttrs: (d) => ({
        src: d.getAttribute("src"), alt: d.getAttribute("alt"), title: d.getAttribute("title"), extra: extraOf(d),
      }) }],
      toDOM: (n) => ["img", attrsOut(n.attrs.extra, { src: n.attrs.src, alt: n.attrs.alt, title: n.attrs.title })],
    },
    hard_break: {
      inline: true, group: "inline", selectable: false,
      attrs: Object.assign({}, EX),
      parseDOM: [{ tag: "br", getAttrs: (d) => ({ extra: extraOf(d) }) }],
      toDOM: (n) => ["br", attrsOut(n.attrs.extra)],
    },
  },
  // Order is nesting order when serialised: <a><strong><em><code>.
  marks: {
    link: {
      attrs: { href: {}, title: { default: null }, extra: { default: [] } },
      inclusive: false,
      parseDOM: [{ tag: "a[href]", getAttrs: (d) => ({ href: d.getAttribute("href"), title: d.getAttribute("title"), extra: extraOf(d) }) }],
      toDOM: (m) => ["a", attrsOut(m.attrs.extra, { href: m.attrs.href, title: m.attrs.title })],
    },
    strong: {
      attrs: { extra: { default: [] }, tag: { default: "strong" } },
      parseDOM: [
        { tag: "strong", getAttrs: (d) => ({ extra: extraOf(d) }) },
        // Google Docs wraps a paste in <b style="font-weight:normal">.
        { tag: "b", getAttrs: (d) => (/font-weight:\s*(normal|[1-4]00)/.test(d.getAttribute("style") || "") ? false : { extra: extraOf(d), tag: "b" }) },
      ],
      toDOM: (m) => [m.attrs.tag, attrsOut(m.attrs.extra)],
    },
    em: {
      attrs: { extra: { default: [] }, tag: { default: "em" } },
      parseDOM: [
        { tag: "em", getAttrs: (d) => ({ extra: extraOf(d) }) },
        { tag: "i", getAttrs: (d) => ({ extra: extraOf(d), tag: "i" }) },
      ],
      toDOM: (m) => [m.attrs.tag, attrsOut(m.attrs.extra)],
    },
    code: {
      attrs: { extra: { default: [] } },
      parseDOM: [{ tag: "code", getAttrs: (d) => ({ extra: extraOf(d) }) }],
      toDOM: (m) => ["code", attrsOut(m.attrs.extra)],
    },
    span: {
      attrs: { tag: { default: "span" }, extra: { default: [] } },
      excludes: "",
      parseDOM: SPAN_TAGS.map((t) => ({ tag: t, getAttrs: (d) => ({ tag: t, extra: extraOf(d) }) })),
      toDOM: (m) => [m.attrs.tag, attrsOut(m.attrs.extra)],
    },
  },
});
