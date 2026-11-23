// skills/annotate/static/edit-diff.js
/* Edit diff: which words did the reader insert or change?
 *
 * Pure text, no DOM. Both strings are cut into words and whitespace runs and
 * diffed by LCS over those tokens, so the answer is whole-word granular and a
 * repeated word ("same same" -> "same NEW same") is not blamed.
 *
 * changedRuns gives offsets in `after` of every inserted or replaced run. A
 * pure deletion leaves nothing of the reader's in `after`, so it yields none.
 * wordDiff gives the eq/del/ins stream the dock row and conflict view render.
 *
 * LCS is quadratic, so a side above CAP tokens is not diffed: the whole
 * `after` counts as one changed run.
 */
(function () {
  "use strict";

  const CAP = 4000;

  // An HTML tag is a token of its own: glued to the word beside it
  // (`jumps.</p>`), a one-word edit would read as a change to the tag too.
  // A `<` that opens no tag is text.
  const TAG = /<\/?[A-Za-z][\w:-]*(?:\s[^<>]*)?\/?>/;
  const TOKEN = new RegExp("\\s+|" + TAG.source + "|[^\\s<]+|<", "g");
  function tokens(s) { return s.match(TOKEN) || []; }
  function isSpace(t) { return /^\s/.test(t); }

  // [{op, text}] one per token, in order; null when over the cap.
  function ops(before, after) {
    const a = tokens(before), b = tokens(after);
    // Common head and tail need no table, and are most of a small edit.
    let h = 0;
    while (h < a.length && h < b.length && a[h] === b[h]) h++;
    let t = 0;
    while (t < a.length - h && t < b.length - h &&
           a[a.length - 1 - t] === b[b.length - 1 - t]) t++;
    const A = a.slice(h, a.length - t), B = b.slice(h, b.length - t);
    if (A.length > CAP || B.length > CAP) return null;
    const out = [];
    for (let i = 0; i < h; i++) out.push({ op: "eq", text: a[i] });
    const n = A.length, m = B.length, w = m + 1;
    const L = new Uint16Array((n + 1) * w);
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        L[i * w + j] = A[i] === B[j]
          ? L[(i + 1) * w + j + 1] + 1
          : Math.max(L[(i + 1) * w + j], L[i * w + j + 1]);
      }
    }
    let i = 0, j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && A[i] === B[j]) { out.push({ op: "eq", text: A[i] }); i++; j++; }
      else if (i < n && (j >= m || L[(i + 1) * w + j] >= L[i * w + j + 1])) {
        out.push({ op: "del", text: A[i++] });
      } else out.push({ op: "ins", text: B[j++] });
    }
    for (let k = a.length - t; k < a.length; k++) out.push({ op: "eq", text: a[k] });
    return out;
  }

  function wordDiff(before, after) {
    const o = ops(before, after);
    if (!o) {
      const r = [];
      if (before) r.push({ op: "del", text: before });
      if (after) r.push({ op: "ins", text: after });
      return r;
    }
    const merged = [];
    for (const x of o) {
      const last = merged[merged.length - 1];
      if (last && last.op === x.op) last.text += x.text;
      else merged.push({ op: x.op, text: x.text });
    }
    return merged;
  }

  function changedRuns(before, after) {
    const o = ops(before, after);
    if (!o) return trim(after, [{ start: 0, end: after.length }]);
    const runs = [];
    let pos = 0, cur = null;
    for (const x of o) {
      if (x.op === "ins") {
        if (!cur) { cur = { start: pos, end: pos }; runs.push(cur); }
        pos += x.text.length;
        cur.end = pos;
      } else if (x.op === "eq") {
        // Whitespace between two changed words does not end the run, so a
        // rewritten sentence is one run, not one per word.
        if (!isSpace(x.text)) cur = null;
        pos += x.text.length;
      }
      // del: nothing in `after`, and it does not end a run either.
    }
    return trim(after, runs);
  }

  function trim(text, runs) {
    const out = [];
    for (const r of runs) {
      let s = r.start, e = r.end;
      while (s < e && /\s/.test(text[s])) s++;
      while (e > s && /\s/.test(text[e - 1])) e--;
      if (e > s) out.push({ start: s, end: e });
    }
    return out;
  }

  window.AnnotateEditDiff = { changedRuns, wordDiff };
})();
