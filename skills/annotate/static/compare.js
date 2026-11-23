// annotate skill — the `compare` kind's line diff.
//
// A pure function of two strings, so tests/compare.test.cjs runs it under node
// and asserts on the rows themselves. script-blocks.js's renderCompare only
// paints what this returns.
//
// alignLines(before, after) → rows for a split view, GitHub style:
//   { left: {n, text, t: "same"|"del"} | null,
//     right: {n, text, t: "same"|"add"} | null }
// Unchanged lines sit on both sides of one row. Between two unchanged lines,
// the run of removed lines and the run of added lines share rows top-down, so
// a changed line sits beside what replaced it; the longer run's tail faces a
// filler (null). `n` is the line's 1-based number on its own side.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateCompare = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Cells of the LCS table we are willing to allocate ((n+1)·(m+1) Uint32s,
  // ~8 MB). Past it the differing middle is shown as one removed run beside
  // one added run, which is still a correct, if coarser, picture.
  const MAX_CELLS = 2000000;

  // "" is no lines at all (a new or deleted file); one trailing newline is
  // the end of the last line, not an empty line after it.
  function splitLines(s) {
    const text = String(s == null ? "" : s).replace(/\r\n?/g, "\n");
    if (text === "") return [];
    return text.replace(/\n$/, "").split("\n");
  }

  // Edit script over lines: [{op: "=", a, b} | {op: "-", a} | {op: "+", b}].
  function lineOps(a, b) {
    let pre = 0;
    while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
    let suf = 0;
    while (suf < a.length - pre && suf < b.length - pre
           && a[a.length - 1 - suf] === b[b.length - 1 - suf]) suf++;
    const ops = [];
    for (let i = 0; i < pre; i++) ops.push({ op: "=", a: i, b: i });
    const A = a.slice(pre, a.length - suf), B = b.slice(pre, b.length - suf);
    const n = A.length, m = B.length;
    if ((n + 1) * (m + 1) > MAX_CELLS) {
      for (let i = 0; i < n; i++) ops.push({ op: "-", a: pre + i });
      for (let j = 0; j < m; j++) ops.push({ op: "+", b: pre + j });
    } else {
      // L[i][j] = LCS length of A[i..] and B[j..].
      const W = m + 1;
      const L = new Uint32Array((n + 1) * W);
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          L[i * W + j] = A[i] === B[j] ? L[(i + 1) * W + j + 1] + 1
            : Math.max(L[(i + 1) * W + j], L[i * W + j + 1]);
        }
      }
      let i = 0, j = 0;
      while (i < n || j < m) {
        if (i < n && j < m && A[i] === B[j]) { ops.push({ op: "=", a: pre + i++, b: pre + j++ }); }
        // Deletions first, so a changed line's old text precedes its new one.
        else if (i < n && (j >= m || L[(i + 1) * W + j] >= L[i * W + j + 1])) ops.push({ op: "-", a: pre + i++ });
        else ops.push({ op: "+", b: pre + j++ });
      }
    }
    for (let k = suf; k > 0; k--) ops.push({ op: "=", a: a.length - k, b: b.length - k });
    return ops;
  }

  function alignLines(before, after) {
    const a = splitLines(before), b = splitLines(after);
    const rows = [];
    let dels = [], adds = [];
    const flush = () => {
      for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
        const i = dels[k], j = adds[k];
        rows.push({
          left: i === undefined ? null : { n: i + 1, text: a[i], t: "del" },
          right: j === undefined ? null : { n: j + 1, text: b[j], t: "add" },
        });
      }
      dels = []; adds = [];
    };
    for (const o of lineOps(a, b)) {
      if (o.op === "-") dels.push(o.a);
      else if (o.op === "+") adds.push(o.b);
      else {
        flush();
        rows.push({ left: { n: o.a + 1, text: a[o.a], t: "same" },
                    right: { n: o.b + 1, text: b[o.b], t: "same" } });
      }
    }
    flush();
    return rows;
  }

  return { splitLines, lineOps, alignLines };
});
