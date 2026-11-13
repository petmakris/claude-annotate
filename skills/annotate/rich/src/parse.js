// The stored text cut into top-level blocks, each with its exact
// source range, and each parsed into the editor's nodes.
//
// A "chunk" is { from, to, fmt: "html" | "md", nodes: [Node] }. The text
// between chunks (blank lines, newlines, nothing) is a "gap" and is kept as
// it is.
import { DOMParser as PMDOMParser } from "prosemirror-model";
import { schema } from "./schema.js";

export const pmParser = PMDOMParser.fromSchema(schema);

function htmlToNodes(html) {
  const t = document.createElement("template");
  t.innerHTML = html;
  const doc = pmParser.parse(t.content);
  const out = [];
  doc.forEach((n) => out.push(n));
  // An empty paragraph from an empty or comment-only run is not a block.
  if (out.length === 1 && out[0].type.name === "paragraph" && !out[0].content.size && !html.includes("<p")) return [];
  return out;
}

// ── HTML sections ────────────────────────────────────────────────────────
const BLOCK = new Set(("address article aside blockquote details dialog dd div dl dt fieldset "
  + "figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr li main nav ol p pre "
  + "section table thead tbody tfoot tr td th caption ul summary").split(" "));
const VOID = new Set("area base br col embed hr img input link meta param source track wbr".split(" "));
const RAW = new Set(["script", "style", "textarea", "title"]);

// Top-level elements of `src` with their ranges; inline runs between them
// grouped as one range. Returns null if the tags do not balance.
function topLevelHtml(src) {
  const items = []; // {from, to, block}
  let i = 0, depth = 0, start = -1, startTag = "";
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:[^>"']|"[^"]*"|'[^']*')*?)(\/?)>/y;
  let inlineFrom = -1;
  const flushInline = (to) => {
    if (inlineFrom >= 0) {
      if (src.slice(inlineFrom, to).trim()) {
        // trim the run's surrounding whitespace into the gaps
        let a = inlineFrom, b = to;
        while (a < b && /\s/.test(src[a])) a++;
        while (b > a && /\s/.test(src[b - 1])) b--;
        items.push({ from: a, to: b, block: false });
      }
      inlineFrom = -1;
    }
  };
  while (i < src.length) {
    if (src.startsWith("<!--", i)) {
      const e = src.indexOf("-->", i + 4);
      const end = e < 0 ? src.length : e + 3;
      if (depth === 0 && inlineFrom < 0) inlineFrom = i;
      i = end;
      continue;
    }
    if (src[i] === "<") {
      tagRe.lastIndex = i;
      const m = tagRe.exec(src);
      if (m) {
        const close = m[1] === "/", name = m[2].toLowerCase(), self = m[4] === "/" || VOID.has(name);
        const end = tagRe.lastIndex;
        if (depth === 0 && !close) {
          if (BLOCK.has(name)) {
            flushInline(i);
            if (self) { items.push({ from: i, to: end, block: true }); i = end; continue; }
            start = i; startTag = name; depth = 1;
            if (RAW.has(name)) {
              const e = src.toLowerCase().indexOf("</" + name, end);
              if (e < 0) return null;
              i = e;
              continue;
            }
            i = end;
            continue;
          }
          if (inlineFrom < 0) inlineFrom = i;
          i = end;
          continue;
        }
        if (depth > 0) {
          if (close) {
            depth--;
            if (depth === 0) {
              if (name !== startTag) return null;
              items.push({ from: start, to: end, block: true });
            }
          } else if (!self) depth++;
          i = end;
          continue;
        }
        // a closing tag at depth 0: an inline element closing
        if (inlineFrom < 0) inlineFrom = i;
        i = end;
        continue;
      }
    }
    if (depth === 0 && inlineFrom < 0 && !/\s/.test(src[i])) inlineFrom = i;
    i++;
  }
  if (depth !== 0) return null;
  flushInline(src.length);
  return items;
}

export function chunksHtml(src) {
  const items = topLevelHtml(src);
  const whole = () => [{ from: 0, to: src.length, fmt: "html", nodes: htmlToNodes(src) }];
  if (!items) return { chunks: whole(), split: false };
  const chunks = items.map((it) => ({ from: it.from, to: it.to, fmt: "html", nodes: htmlToNodes(src.slice(it.from, it.to)) }));
  // Safety: the pieces must parse to what the whole parses to.
  const all = htmlToNodes(src);
  const flat = chunks.flatMap((c) => c.nodes);
  if (flat.length !== all.length || flat.some((n, k) => !n.eq(all[k]))) return { chunks: whole(), split: false };
  return { chunks, split: true };
}

// ── markdown sections ────────────────────────────────────────────────────
let mdi = null;
export function md() {
  if (!mdi) {
    mdi = window.markdownit({ html: true, linkify: true, typographer: false, breaks: false });
    mdi.disable("code");
  }
  return mdi;
}

// `refs`: the page's link reference definitions ([x]: url), so that a
// block parsed alone still resolves [text][x].
export function mdToNodes(text, refs) {
  const env = refs ? { references: Object.assign({}, refs) } : {};
  return htmlToNodes(md().render(text, env));
}

export function chunksMd(src) {
  const env = {};
  const tokens = md().parse(src, env);
  // markdown-it counts lines after turning \r\n and a lone \r into \n, so
  // its line maps index lines split on all three.
  const lineStart = [0], breakLen = [];
  for (let k = 0; k < src.length; k++) {
    const c = src[k];
    if (c === "\r" && src[k + 1] === "\n") { breakLen.push(2); lineStart.push(k + 2); k++; }
    else if (c === "\r" || c === "\n") { breakLen.push(1); lineStart.push(k + 1); }
  }
  const lineEnd = (l) => (l < lineStart.length - 1 ? lineStart[l + 1] - breakLen[l] : src.length);
  const chunks = [];
  for (const t of tokens) {
    if (t.level !== 0 || t.nesting === -1 || !t.map) continue;
    let from = lineStart[t.map[0]];
    let to = lineEnd(t.map[1] - 1);
    while (to > from && /\s/.test(src[to - 1])) to--;
    const text = src.slice(from, to);
    chunks.push({ from, to, fmt: t.type === "html_block" ? "html" : "md", text });
  }
  // Link reference definitions are not tokens. Their lines become chunks
  // of their own with no nodes: never shown, never matched against the
  // edited document, always written back in place (see save.js). Each block
  // is parsed with the definitions known, so its [text][x] links resolve.
  const covered = new Uint8Array(lineStart.length);
  for (const t of tokens) if (t.level === 0 && t.nesting !== -1 && t.map) covered.fill(1, t.map[0], t.map[1]);
  for (let l = 0; l < lineStart.length; l++) {
    if (covered[l] || !src.slice(lineStart[l], lineEnd(l)).trim()) continue;
    let e = l;
    while (e + 1 < lineStart.length && !covered[e + 1] && src.slice(lineStart[e + 1], lineEnd(e + 1)).trim()) e++;
    let from = lineStart[l], to = lineEnd(e);
    while (from < to && /\s/.test(src[from])) from++;
    while (to > from && /\s/.test(src[to - 1])) to--;
    chunks.push({ from, to, fmt: "md", text: "", bare: true });
    l = e;
  }
  chunks.sort((x, y) => x.from - y.from);
  const refs = env.references && Object.keys(env.references).length ? env.references : null;
  for (const c of chunks) { c.nodes = c.bare ? [] : mdToNodes(c.text, refs); delete c.text; }
  // Safety, as for HTML: the blocks parsed alone must equal the whole.
  const all = mdToNodes(src);
  const flat = chunks.flatMap((c) => c.nodes);
  if (flat.length !== all.length || flat.some((n, k) => !n.eq(all[k]))) {
    return { chunks: [{ from: 0, to: src.length, fmt: "md", nodes: all }], split: false, refs };
  }
  return { chunks, split: true, refs };
}

// The most used bullet in the stored markdown, for new lists.
export function bulletOf(src) {
  const n = { "-": 0, "*": 0, "+": 0 };
  for (const m of src.matchAll(/^\s*([-*+]) /gm)) n[m[1]]++;
  const [best, count] = Object.entries(n).sort((a, b) => b[1] - a[1])[0];
  return count ? best : "-";
}

export function chunksFor(src, fmt) {
  return fmt === "html" ? chunksHtml(src) : chunksMd(src);
}

// Re-parse a piece of stored text in a format, for the save's check.
export function reparse(text, fmt, refs) {
  return fmt === "html" ? htmlToNodes(text) : mdToNodes(text, refs);
}

// HTML when the first non-blank block is an HTML element and every
// top-level block is one: by the HTML splitter and by markdown-it, which is
// how the page renders it (a blank line inside a <div> hands the rest back
// to markdown).
export function formatOf(text) {
  if (!/^\s*<[a-zA-Z]/.test(text)) return "md";
  const items = topLevelHtml(text);
  if (!items || !items.length || items.some((it) => !it.block)) return "md";
  const top = md().parse(text, {}).filter((t) => t.level === 0 && t.nesting !== -1);
  return top.length && top.every((t) => t.type === "html_block") ? "html" : "md";
}
