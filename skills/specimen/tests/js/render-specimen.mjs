/* render-specimen.mjs — draw a pushed specimen with no browser and report what
 * came out.
 *
 * The page's honesty claims are claims about the DOM: every anchor
 * `build_items` emits must reach a row, and no section may wear a badge with
 * nothing behind it. Asserting that in Python alone would mean re-implementing
 * specimen.js's dispatch in the test, which would then pass while the real
 * renderer was wrong — exactly how `behaviour` got shipped as "unhandled".
 * So the real file is executed, against a DOM small enough to read.
 *
 * Usage: node render-specimen.mjs <items.json>
 * The input is the daemon's bulk shape: {"<anchor>": {"body": {...}}, ...}.
 * Prints JSON: {anchors, rows, tree, sections, header}.
 *
 * `rows` maps each anchor to a LIST of occurrences, not to one. The page draws
 * the populated instance as a tree, and one type occurs many times in one tree
 * (three Contributor items, all with a `proposedRiskContribution` row). Every
 * one of those rows carries the same position-free anchor `<fqn>#<field>`, so a
 * comment thread still survives a re-push. A map keyed anchor -> one row would
 * silently keep the last occurrence and hide the null on the first, which is
 * the exact failure this page exists to prevent.
 *
 * `tree` is the nested shape of the instance section: each node's label, its
 * type, its anchor if it has one, the text of its cells, and its children. It
 * is what lets a test assert that a nested object draws its own fields INSIDE
 * its parent rather than as a dash and a filename somewhere else on the page.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const items = JSON.parse(readFileSync(process.argv[2], "utf8"));

function node(tag) {
  return {
    tag,
    className: "",
    attrs: {},
    children: [],
    _text: "",
    set textContent(v) { this._text = String(v); this.children.length = 0; },
    get textContent() { return this._text; },
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
  };
}

function textNode(t) {
  const n = node("#text");
  n.textContent = t;
  return n;
}

const root = node("main");
root.attrs["data-wc-root"] = "";

globalThis.document = {
  createElement: node,
  createTextNode: textNode,
  querySelector: () => root,
};
// The page reads its initial view from the URL, so `#table` is how a link
// points at one. The harness passes it the same way.
globalThis.location = { hash: process.argv[3] || "" };
globalThis.window = {
  location: globalThis.location,
  WebCompanion: {
    api: { fetchJSON: () => Promise.resolve(items) },
    init: () => {},
  },
};

const source = readFileSync(
  join(here, "..", "..", "webcompanion", "static", "specimen.js"), "utf8");
// eslint-disable-next-line no-new-func
new Function(source)();

await new Promise((r) => setTimeout(r, 0));
await new Promise((r) => setTimeout(r, 0));

const anchors = [];
const rows = {};
const sections = [];
// Every type name on the page is a pill that copies the name it stands for.
const pills = [];

function textOf(n) {
  if (n.tag === "#text") return n.textContent;
  return n.textContent + n.children.map(textOf).join("");
}

function firstWithClass(n, cls) {
  for (const child of n.children) {
    if (String(child.className).split(/\s+/).includes(cls)) return child;
    const deeper = firstWithClass(child, cls);
    if (deeper) return deeper;
  }
  return null;
}

function hasClass(n, cls) {
  return String((n && n.className) || "").split(/\s+/).includes(cls);
}

// A row's cells are its leaf spans. The page groups the declaration detail
// (declared type, provenance, source, the jump) into one trailing element so
// it can be dimmed and pushed right as a unit; a test asking for the source
// reference is asking about the row, not about that grouping.
function cellsOf(row) {
  const out = [];
  for (const child of row.children) {
    if (hasClass(child, "specimen-meta-group")) {
      for (const inner of child.children) {
        out.push({ className: inner.className, text: textOf(inner) });
      }
    } else {
      out.push({ className: child.className, text: textOf(child) });
    }
  }
  return out;
}

// The instance tree, read back out of the DOM. A node is any element carrying
// `data-node-kind`; its children are the nodes nested anywhere below it, with
// the rows that belong to it kept as `cells`.
function treeOf(n) {
  const node = {
    kind: n.attrs["data-node-kind"],
    label: "",
    type: n.attrs["data-node-type"] || null,
    anchor: n.attrs["data-wc-anchor"] || null,
    cells: [],
    children: [],
  };
  const head = hasClass(n, "specimen-field-row") ? n : firstWithClass(n, "specimen-field-row");
  if (head) {
    node.cells = cellsOf(head);
    const label = firstWithClass(head, "specimen-field");
    node.label = label ? textOf(label) : "";
    node.anchor = head.attrs["data-wc-anchor"] || node.anchor;
  }
  (function descend(x) {
    for (const child of x.children) {
      if (child.attrs && child.attrs["data-node-kind"]) node.children.push(treeOf(child));
      else descend(child);
    }
  })(n);
  return node;
}

function walk(n) {
  if (n.attrs && n.attrs["data-copy"]) {
    pills.push({ text: textOf(n), copy: n.attrs["data-copy"] });
  }
  if (n.attrs && n.attrs["data-wc-anchor"]) {
    const anchor = n.attrs["data-wc-anchor"];
    anchors.push(anchor);
    (rows[anchor] = rows[anchor] || []).push({
      className: n.className,
      cells: cellsOf(n),
    });
  }
  if (n.tag === "section") {
    const heading = n.children.find((c) => c.tag === "h2");
    const badge = firstWithClass(n, "specimen-badge");
    const reason = firstWithClass(n, "specimen-reason");
    sections.push({
      fqn: heading ? textOf(heading) : "",
      className: n.className,
      badge: badge ? textOf(badge) : null,
      reason: reason ? textOf(reason) : null,
      rows: (function count(x) {
        let seen = x.attrs && x.attrs["data-wc-anchor"] ? 1 : 0;
        for (const c of x.children) seen += count(c);
        return seen;
      })(n),
    });
  }
  for (const child of n.children) walk(child);
}

walk(root);

// The table view: one record per row, one column per field of that record's
// type. Read back as {type, columns, rows} so a test can assert that two
// instances of one type sit under each other.
const tables = [];
(function findTables(n) {
  for (const child of n.children) {
    if (child.attrs && child.attrs["data-record-type"]) {
      // A composite column opens into a spanning group header with its fields
      // underneath, so the header is a TREE, not a row. `columns` is the leaf
      // columns in order — what a body row actually lines up against — and
      // `groups` is the spanning headers above them.
      const columns = [];
      const groups = [];
      const rows = [];
      let headerRows = 0;
      (function scan(x) {
        for (const kid of x.children) {
          if (kid.tag === "thead") { headerRows = kid.children.length; scan(kid); continue; }
          if (kid.attrs && kid.attrs["data-col-path"]) {
            const name = firstWithClass(kid, "specimen-th-name");
            const entry = {
              name: name ? textOf(name) : textOf(kid),
              path: kid.attrs["data-col-path"],
              anchor: kid.attrs["data-wc-anchor"] || null,
              colspan: Number(kid.attrs.colspan || 1),
              index: Number(kid.attrs["data-col-index"] || 0),
            };
            if (hasClass(kid, "specimen-grouphead")) groups.push(entry);
            else columns.push(entry);
            continue;
          }
          if (hasClass(kid, "specimen-record-row")) {
            const cells = kid.children
              .filter((c) => !hasClass(c, "specimen-record-path"))
              .map((c) => ({ text: textOf(c), colspan: Number(c.attrs.colspan || 1) }));
            const label = kid.children.find((c) => hasClass(c, "specimen-record-path"));
            rows.push({ path: label ? textOf(label) : "", cells });
            continue;
          }
          scan(kid);
        }
      })(child);
      // Left-to-right, which is the order a body row's cells line up against.
      // DOM order is level by level, so it is not the same thing.
      columns.sort((a, b) => a.index - b.index);
      tables.push({ type: child.attrs["data-record-type"], columns, groups, rows, headerRows });
    } else {
      findTables(child);
    }
  }
})(root);

const treeSection = (function find(n) {
  for (const child of n.children) {
    if (hasClass(child, "specimen-tree")) return child;
    const deeper = find(child);
    if (deeper) return deeper;
  }
  return null;
})(root);

let tree = null;
if (treeSection) {
  for (const child of treeSection.children) {
    if (child.attrs && child.attrs["data-node-kind"]) { tree = treeOf(child); break; }
  }
}

process.stdout.write(JSON.stringify({
  anchors,
  pills,
  rows,
  tables,
  tree,
  sections,
  header: textOf(root.children[0] || node("x")),
}, null, 2));
