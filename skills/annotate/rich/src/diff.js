// Character diff (Myers) and the three-way patch the minimal save
// is built on.
//
// threeWay(s0, s1, src): s0 is how the editor would write a block as it was
// opened, s1 how it writes the block now, src the block's stored bytes. The
// edit s0 → s1 is replayed onto src wherever the edited stretch of s0 is
// text src has byte for byte. Anything else returns null (the caller then
// stores s1).

// Myers O((N+M)D): [op, text] runs, op = 0 equal, -1 delete, 1 insert.
export function diff(a, b, maxD = 4000) {
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let suf = 0;
  while (suf < a.length - pre && suf < b.length - pre && a[a.length - 1 - suf] === b[b.length - 1 - suf]) suf++;
  const A = a.slice(pre, a.length - suf), B = b.slice(pre, b.length - suf);
  const mid = myers(A, B, maxD);
  const out = [];
  const push = (op, t) => {
    if (!t) return;
    const l = out[out.length - 1];
    if (l && l[0] === op) l[1] += t; else out.push([op, t]);
  };
  push(0, a.slice(0, pre));
  if (mid) for (const [op, t] of mid) push(op, t);
  else { push(-1, A); push(1, B); }
  push(0, a.slice(a.length - suf));
  return out;
}

function myers(a, b, maxD) {
  const n = a.length, m = b.length;
  if (!n) return [[1, b]];
  if (!m) return [[-1, a]];
  const max = Math.min(n + m, maxD);
  const off = max + 1;
  const v = new Int32Array(2 * max + 3);
  const trace = [];
  for (let d = 0; d <= max; d++) {
    trace.push(v.slice());
    for (let k = -d; k <= d; k += 2) {
      let x;
      if (k === -d || (k !== d && v[off + k - 1] < v[off + k + 1])) x = v[off + k + 1];
      else x = v[off + k - 1] + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) { x++; y++; }
      v[off + k] = x;
      if (x >= n && y >= m) return backtrack(trace, a, b, off, d);
    }
  }
  return null;
}

function backtrack(trace, a, b, off, dEnd) {
  const ops = [];
  let x = a.length, y = b.length;
  for (let d = dEnd; d > 0; d--) {
    const v = trace[d];
    const k = x - y;
    const prevK = (k === -d || (k !== d && v[off + k - 1] < v[off + k + 1])) ? k + 1 : k - 1;
    const px = v[off + prevK], py = px - prevK;
    while (x > px && y > py) { ops.push([0, a[x - 1]]); x--; y--; }
    if (x === px) { ops.push([1, b[y - 1]]); y--; } else { ops.push([-1, a[x - 1]]); x--; }
  }
  while (x > 0 && y > 0) { ops.push([0, a[x - 1]]); x--; y--; }
  ops.reverse();
  const out = [];
  for (const [op, c] of ops) {
    const l = out[out.length - 1];
    if (l && l[0] === op) l[1] += c; else out.push([op, c]);
  }
  return out;
}

// Edits s0 → s1 as {from, to, text} over s0. Neighbouring delete and insert
// runs are one edit.
function edits(s0, s1) {
  const out = [];
  let i = 0, cur = null;
  for (const [op, t] of diff(s0, s1)) {
    if (op === 0) { if (cur) { out.push(cur); cur = null; } i += t.length; continue; }
    if (!cur) cur = { from: i, to: i, text: "" };
    if (op === -1) { i += t.length; cur.to = i; } else cur.text += t;
  }
  if (cur) out.push(cur);
  return out;
}

// opts.protect: [from, to) ranges of src (code) where that never happens.
// opts.blockBreaks (markdown): an inserted blank line (Enter splitting a
// paragraph) takes the place of the whitespace the split point had in src,
// so a split at a space or at the end of a wrapped line stores exactly one
// blank line, not a blank line plus the old space or newline.
const WS = /[ \t]/;
const LINE = (s, k) => (s[k] === "\r" && s[k + 1] === "\n" ? 2 : s[k] === "\r" || s[k] === "\n" ? 1 : 0);
function absorb(src, p) {
  const t = p.text.replace(/\r\n?/g, "\n");
  if (!/\n[ \t]*\n/.test(t)) return p;
  let { from, to } = p;
  let took = false;
  if (/^[ \t]*\n/.test(t)) {
    while (from > 0 && WS.test(src[from - 1])) from--;
    // the line break src had just before the split point (one, not a blank line)
    const n = src[from - 1] === "\n" && src[from - 2] === "\r" ? 2 : (src[from - 1] === "\n" || src[from - 1] === "\r") ? 1 : 0;
    if (n && !LINE(src, from - n - 1) && !(src[from - n - 1] === "\n" && src[from - n - 2] === "\r")) { from -= n; took = true; }
  }
  if (!took && /\n[ \t]*$/.test(t)) {
    while (to < src.length && WS.test(src[to])) to++;
    const n = LINE(src, to);
    if (n && !LINE(src, to + n)) to += n;
  }
  return { from, to, text: p.text };
}

export function threeWay(s0, s1, src, opts = {}) {
  if (s0 === s1) return src;
  if (s0 === src && !opts.blockBreaks) return s1;
  // Where each char of s0 sits in src, if src has it (-1 if not).
  const at = new Int32Array(s0.length).fill(-1);
  let i = 0, j = 0;
  for (const [op, t] of diff(s0, src)) {
    if (op === 0) { for (let k = 0; k < t.length; k++) at[i + k] = j + k; i += t.length; j += t.length; }
    else if (op === -1) i += t.length;
    else j += t.length;
  }
  const es = edits(s0, s1);
  const patches = [];
  for (const e of es) {
    let from, to;
    if (e.to > e.from) {
      // Every deleted char is in src, contiguously.
      let ok = true;
      for (let k = e.from; k < e.to && ok; k++) {
        if (at[k] < 0 || (k > e.from && at[k] !== at[k - 1] + 1)) ok = false;
      }
      if (ok) { from = at[e.from]; to = at[e.to - 1] + 1; }
      else {
        // Or whitespace the editor writes differently (a space where src
        // wraps the line): it is src's whitespace between the same
        // neighbours that goes.
        const l = e.from > 0 ? at[e.from - 1] : -1;
        const r = e.to < s0.length ? at[e.to] : src.length;
        if (!/^\s+$/.test(s0.slice(e.from, e.to)) || (e.from > 0 && l < 0) || r < 0 || r <= l + 1
          || !/^\s+$/.test(src.slice(l + 1, r))) return null;
        from = l + 1; to = r;
      }
    } else {
      // An insertion point: the chars either side must be src's, adjacent.
      const l = e.from > 0 ? at[e.from - 1] : -2;
      const r = e.from < s0.length ? at[e.from] : -2;
      // Otherwise it goes beside the side src has; the caller re-parses
      // the result and refuses it if that guess changed the meaning.
      if (l >= 0 && r >= 0) { if (r !== l + 1) return null; from = to = r; }
      else if (l >= 0) from = to = l + 1;
      else if (r >= 0) from = to = r;
      else if (l === -2 && r === -2) from = to = 0;
      else return null;
    }
    const inCode = (opts.protect || []).some(([a, b]) => from >= a && to <= b);
    patches.push(opts.blockBreaks && !inCode ? absorb(src, { from, to, text: e.text }) : { from, to, text: e.text });
  }
  for (let k = 1; k < patches.length; k++) if (patches[k].from < patches[k - 1].to) return null;
  let out = src;
  for (let k = patches.length - 1; k >= 0; k--) {
    const p = patches[k];
    out = out.slice(0, p.from) + p.text + out.slice(p.to);
  }
  return out;
}
