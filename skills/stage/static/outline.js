// The text alternative of a board: what a screen reader (or the call page's "Read the board as text") gets of a board
// that is drawn. Pure: it reads the DOM the board already holds and writes nothing. A table is read row by row with
// its column names; any other board is the list of arrows or values the server drew for it (.vz-reading, .m-reading), else
// its keyed parts (nodes, boxes, steps, slide parts) in order.
const MAX_LINES = 200;
const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();

export function outlineOf(box) {
  if (!box) return { kind: "", head: [], lines: [] };
  const table = box.querySelector("table");
  if (table) {
    const head = [...table.querySelectorAll("thead th")].map((c) => clean(c.textContent));
    const lines = [...table.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c, i) => {
      const t = clean(c.textContent);
      return head[i] && t ? `${head[i]}: ${t}` : t;
    }).filter(Boolean).join("; "));
    return { kind: "table", head, lines: lines.slice(0, MAX_LINES) };
  }
  const lines = [], seen = new Set();
  const add = (t) => { t = clean(t); if (t && !seen.has(t)) { seen.add(t); lines.push(t); } };
  for (const li of box.querySelectorAll(".vz-reading li, .m-reading li")) add(li.textContent);  // the server's own sentences, when it made them
  if (!lines.length) for (const el of box.querySelectorAll("[data-key]")) {
    if (/^(edge|route|zone|mode):/.test(el.dataset.key || "")) continue;
    add(el.textContent);
  }
  if (!lines.length) add(box.textContent);
  return { kind: "board", head: [], lines: lines.slice(0, MAX_LINES) };
}
