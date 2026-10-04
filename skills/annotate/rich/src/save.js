// The minimal-change save.
//
// The stored text is   gap0 chunk0 gap1 chunk1 … chunkN-1 gapN.
// The edited document's top-level nodes are lined up against the chunks'
// nodes (LCS on node equality). A chunk whose nodes all come through
// unchanged, in a row, is written as its original bytes. Everything else is
// a "hunk": a run of removed chunks and a run of new nodes between two kept
// chunks. A hunk is written by replaying the editor's own change onto the
// stored bytes (threeWay), and only if that re-parses to exactly the new
// nodes; otherwise the new nodes are serialised fresh.
//
// Separators: between two kept chunks that were neighbours, the original gap.
// Around a hunk that replaced chunks, the gaps that were outside those
// chunks; the gaps inside them are part of the hunk's bytes. A deleted run
// drops its bytes and the gap on one side of it. Between new nodes, and
// around a hunk that only inserts, the page's usual gap (the most common
// one in the stored text; "\n\n" for markdown when there is none).
//
// Line ends: the serialisers write "\n". In a text whose lines end in
// "\r\n" or a lone "\r", what they write is converted to that before it is
// diffed or stored, so a fresh block never mixes line ends into the page.
import { threeWay } from "./diff.js";
import { nodeToHtml, nodeToMarkdown } from "./serialize.js";
import { reparse } from "./parse.js";

export function eolOf(src) {
  const crlf = (src.match(/\r\n/g) || []).length;
  const cr = (src.match(/\r(?!\n)/g) || []).length;
  const lf = (src.match(/(^|[^\r])\n/g) || []).length;
  if (crlf > cr && crlf > lf) return "\r\n";
  if (cr > crlf && cr > lf) return "\r";
  return "\n";
}

export function plan(src, chunks, fmt, eol = "\n") {
  const gaps = [];
  let at = 0;
  for (const c of chunks) { gaps.push(src.slice(at, c.from)); at = c.to; }
  gaps.push(src.slice(at));
  const inner = gaps.slice(1, -1);
  const counts = {};
  for (const g of inner) counts[g] = (counts[g] || 0) + 1;
  const common = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  const sep = common ? common[0] : (fmt === "md" ? eol + eol : "");
  return { gaps, sep };
}

function lcs(a, b) {
  const n = a.length, m = b.length, w = m + 1;
  const L = new Uint16Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) {
    L[i * w + j] = a[i].eq(b[j]) ? L[(i + 1) * w + j + 1] + 1 : Math.max(L[(i + 1) * w + j], L[i * w + j + 1]);
  }
  const pairs = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i].eq(b[j])) { pairs.push([i, j]); i++; j++; }
    else if (L[(i + 1) * w + j] >= L[i * w + j + 1]) i++;
    else j++;
  }
  return pairs;
}

// How a node is written in this section. In a markdown section a block that
// came from raw HTML is written back as HTML.
function ser(node, fmt, opts) {
  const t = fmt === "html" ? nodeToHtml(node) : nodeToMarkdown(node, opts);
  return opts.eol && opts.eol !== "\n" ? t.replace(/\n/g, opts.eol) : t;
}

// Equal as the page shows them: the same nodes, or, outside code, the same
// HTML once whitespace is collapsed (a paragraph that starts with a space
// after Enter renders as one that does not).
function shown(nodes) {
  const h = nodes.map((n) => nodeToHtml(n)).join("");
  if (h.includes("<pre")) return h;
  return h.replace(/\s+/g, " ").replace(/>\s+/g, ">").replace(/\s+</g, "<");
}
function sameNodes(a, b) {
  if (a.length === b.length && a.every((n, k) => n.eq(b[k]))) return true;
  return shown(a) === shown(b);
}

function isBlankDoc(doc) {
  return doc.childCount === 1 && doc.firstChild.type.name === "paragraph" && !doc.firstChild.content.size;
}

const isEmptyPara = (n) => n.type.name === "paragraph" && !n.content.size;

export function minimalSave(src, chunks, doc, fmt, opts = {}) {
  const stats = { kept: 0, hunks: [], fresh: 0 };
  const eol = opts.eol || "\n";
  // An empty paragraph (Enter pressed twice) is nothing in markdown: it
  // is left out of what is written rather than stored as blank lines.
  const writable = (nodes, f) => (f === "md" ? nodes.filter((n) => !isEmptyPara(n)) : nodes);
  if (!chunks.length) {
    // Nothing but blanks was stored: an editor left empty keeps them.
    if (isBlankDoc(doc)) return { text: src, stats };
    const nodes = []; doc.forEach((n) => nodes.push(n));
    const t = writable(nodes, fmt).map((n) => ser(n, fmt, opts)).join(fmt === "md" ? eol + eol : "");
    stats.hunks.push({ chunks: [0, 0], nodes: [0, nodes.length], how: "fresh" });
    stats.fresh++;
    return { text: t, stats };
  }
  const { gaps, sep } = plan(src, chunks, fmt, eol);
  const orig = [];
  chunks.forEach((c, ci) => c.nodes.forEach((n, k) => orig.push({ n, ci, k })));
  const edited = [];
  doc.forEach((n) => edited.push(n));
  const pairs = lcs(orig.map((o) => o.n), edited);
  // A chunk is kept when every one of its nodes is matched, consecutively.
  const matchOf = new Map(pairs.map(([i, j]) => [i, j]));
  const firstOrig = new Map();
  orig.forEach((o, i) => { if (!firstOrig.has(o.ci)) firstOrig.set(o.ci, i); });
  const kept = new Map(); // ci -> first edited index
  chunks.forEach((c, ci) => {
    if (!c.nodes.length) return; // a chunk with no nodes (a comment) rides along with its hunk
    const i0 = firstOrig.get(ci);
    const js = c.nodes.map((_, k) => matchOf.get(i0 + k));
    if (js.every((j) => j !== undefined) && js.every((j, k) => k === 0 || j === js[k - 1] + 1)) kept.set(ci, js[0]);
  });
  const keptList = [...kept.entries()].sort((a, b) => a[0] - b[0]);
  // Drop kept chunks whose edited positions go backwards (a moved block).
  const mono = [];
  for (const [ci, j] of keptList) if (!mono.length || j > mono[mono.length - 1][1]) mono.push([ci, j]);

  // Pass 1: the steps. A chunk the editor never showed (a comment) at
  // either edge of a hunk is not part of the change: it is written as it
  // was, with its gaps.
  const steps = []; // {keep: c} | {c1, c2, j1, j2}
  const hunk = (c1, c2, j1, j2) => {
    const trail = [];
    while (c1 < c2 && !chunks[c1].nodes.length) steps.push({ keep: c1++, bare: true });
    while (c2 > c1 && !chunks[c2 - 1].nodes.length) trail.unshift(--c2);
    if (c1 !== c2 || j1 !== j2) steps.push({ c1, c2, j1, j2 });
    for (const c of trail) steps.push({ keep: c, bare: true });
  };
  let ci = 0, j = 0;
  for (const [kc, kj] of mono) {
    hunk(ci, kc, j, kj);
    steps.push({ keep: kc });
    ci = kc + 1;
    j = kj + chunks[kc].nodes.length;
  }
  hunk(ci, chunks.length, j, edited.length);

  // A block that was moved is a deletion in one place and an insertion in
  // another. The insertion reuses the deleted block's stored bytes, so a
  // moved paragraph keeps its wrapping and its attributes as written.
  const pool = [];
  for (const st of steps) {
    if (st.keep !== undefined || st.j1 !== st.j2) continue;
    for (let c = st.c1; c < st.c2; c++) if (chunks[c].nodes.length === 1) pool.push(c);
  }
  const reuse = (node) => {
    const k = pool.findIndex((c) => chunks[c].nodes[0].eq(node));
    if (k < 0) return null;
    const c = chunks[pool.splice(k, 1)[0]];
    return src.slice(c.from, c.to);
  };

  // Pass 2: the pieces. {text | null, from: ci, to: ci}
  const pieces = [];
  const keepBare = (c) => pieces.push({ text: src.slice(chunks[c].from, chunks[c].to), from: c, to: c + 1 });
  const deleted = (c1, c2, j1, j2) => {
    // A chunk the editor never showed is not the reader's to delete.
    for (let c = c1; c < c2; c++) {
      if (chunks[c].nodes.length) pieces.push({ text: null, from: c, to: c + 1 });
      else keepBare(c);
    }
    stats.hunks.push({ chunks: [c1, c2], nodes: [j1, j2], how: "deleted" });
  };
  const emit = ({ c1, c2, j1, j2 }) => {
    const fmtOf = c1 < c2 && chunks.slice(c1, c2).every((c) => c.fmt === "html") ? "html" : fmt;
    const newNodes = writable(edited.slice(j1, j2), fmtOf);
    if (!newNodes.length) { if (c1 < c2) deleted(c1, c2, j1, j2); return; }
    let text, how = "fresh";
    if (c1 === c2) {
      let moved = 0;
      text = newNodes.map((n) => { const r = reuse(n); if (r !== null) { moved++; return r; } return ser(n, fmtOf, opts); }).join(sep);
      if (moved === newNodes.length) how = "moved";
    } else {
      const s1 = newNodes.map((n) => ser(n, fmtOf, opts)).join(sep);
      text = s1;
      const srcPart = src.slice(chunks[c1].from, chunks[c2 - 1].to);
      let s0 = "";
      for (let c = c1; c < c2; c++) {
        if (c > c1) s0 += gaps[c];
        s0 += chunks[c].nodes.map((n) => ser(n, fmtOf, opts)).join(sep);
      }
      // Code keeps its blank lines as typed: the blank-line absorb of a
      // paragraph split never reaches inside a code block's bytes.
      const code = [];
      for (let c = c1; c < c2; c++) {
        if (chunks[c].nodes.some((n) => n.type.name === "code_block")) code.push([chunks[c].from - chunks[c1].from, chunks[c].to - chunks[c1].from]);
      }
      const patched = threeWay(s0, s1, srcPart, { blockBreaks: fmtOf === "md", protect: code });
      // A chunk the editor never showed (a link definition, a comment) inside
      // the hunk must come through the replay intact.
      const bare = [];
      for (let c = c1; c < c2; c++) if (!chunks[c].nodes.length) bare.push(src.slice(chunks[c].from, chunks[c].to));
      const intact = (t) => bare.every((b) => t.includes(b));
      if (patched !== null && intact(patched) && sameNodes(reparse(patched, fmtOf, opts.refs), newNodes)) { text = patched; how = "patched"; }
      else {
        how = patched === null ? "fresh (no clean replay)" : "fresh (replay re-parsed differently)";
        if (bare.length) text = [s1, ...bare].join(sep);
      }
    }
    stats.hunks.push({ chunks: [c1, c2], nodes: [j1, j2], how });
    if (how.startsWith("fresh")) stats.fresh++;
    pieces.push({ text, from: c1, to: c2 });
  };
  for (const st of steps) {
    if (st.keep !== undefined) {
      if (st.bare) keepBare(st.keep);
      else { pieces.push({ text: src.slice(chunks[st.keep].from, chunks[st.keep].to), from: st.keep, to: st.keep + 1 }); stats.kept++; }
    } else emit(st);
  }
  // Join. Two pieces that were neighbours in the stored text keep the gap
  // between them; a deleted run in between counts as part of the piece
  // before it, so its own gap goes with it.
  let out = gaps[0];
  let prev = null;
  for (const p of pieces) {
    if (p.text === null) {
      if (prev && prev.to === p.from) prev = { from: prev.from, to: p.to };
      continue;
    }
    if (prev) out += (prev.to > prev.from && p.to > p.from && prev.to === p.from) ? gaps[p.from] : sep;
    out += p.text;
    prev = p;
  }
  out += gaps[gaps.length - 1];
  return { text: out, stats };
}
