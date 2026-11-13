// annotate skill — per-block diff engine.
//
// Pure functions of two strings, deliberately: the pane's whole failure mode
// was invisible because the diff was welded into a DOM renderer and could only
// be inspected by looking at a screenshot. Everything here is executed and
// asserted on directly by tests/diff_engine.test.cjs.
//
// The pipeline is three stages, and each one exists because skipping it
// produced a specific, visible defect:
//
//   parseInline   markdown -> plain text + a per-character format map.
//                 Diffing raw markdown made `**`, `1.` and list dashes into
//                 diffable tokens, so the pane showed punctuation that appears
//                 nowhere in the card above it.
//   splitUnits    text -> paragraphs and list items.
//                 Diffing the block as one string flattened its structure and
//                 let the word-level LCS align across paragraph boundaries.
//   alignUnits    old units + new units -> same / mod / del / ins rows.
//                 Word-level diff is only meaningful INSIDE a pair that stayed
//                 recognisably the same paragraph. Between unrelated
//                 paragraphs it produces noise, not information.
//
// Only after all three does diffChunks run, and it applies a semantic cleanup
// the shipped engine lacked entirely.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateDiff = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Cells of the LCS table we are willing to allocate. The table is
  // (n+1)·(m+1) Uint32s, so 2,000,000 cells is ~8 MB and a couple of
  // milliseconds. Tokens are word-plus-separator, so the cap bites at roughly
  // 700 words per side. Uncapped, a 2000-word block asks for ~61 MB and a
  // 4000-word one for ~244 MB, and the pane runs this over every changed
  // block, so the peaks stack into a frozen tab or a RangeError.
  const MAX_CELLS = 2000000;

  function tokens(s) { return s.split(/(\s+)/).filter((x) => x !== ""); }

  function lcsOps(a, b) {
    const A = tokens(a), B = tokens(b), n = A.length, m = B.length;
    // Too big to align word by word. Fall back to one whole-text replacement:
    // it loses the "which words moved" precision, but it is still a correct
    // description of the change and it always renders.
    if (n * m > MAX_CELLS) return [["-", a], ["+", b]];
    const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1
                                 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const out = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) { out.push(["=", A[i]]); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(["-", A[i]]); i++; }
      else { out.push(["+", B[j]]); j++; }
    }
    while (i < n) out.push(["-", A[i++]]);
    while (j < m) out.push(["+", B[j++]]);
    return out;
  }

  // Ops -> an alternating sequence of {t:"eq"} and {t:"ch", del, ins} chunks.
  // Concatenating eq+del reproduces the old text and eq+ins the new one, which
  // is the invariant every renderer downstream depends on.
  function toChunks(ops) {
    const out = [];
    let del = "", ins = "";
    const flush = () => { if (del || ins) { out.push({ t: "ch", del, ins }); del = ""; ins = ""; } };
    for (const [op, tok] of ops) {
      if (op === "=") {
        flush();
        const last = out[out.length - 1];
        if (last && last.t === "eq") last.s += tok; else out.push({ t: "eq", s: tok });
      } else if (op === "-") del += tok;
      else ins += tok;
    }
    flush();
    return out;
  }

  // Longest equality we will ever absorb, in words. One word is the whole
  // budget on purpose. The length test below is relative, so it loosens as the
  // surrounding edits grow during the fixpoint pass; this cap does not, and it
  // is what stops a two-word survival like "still open" — identical in both
  // versions, and the reader's anchor in the sentence — from being swallowed
  // late in the loop. Anything longer than a single word is a phrase someone
  // can recognise, and hiding it inside a change is a lie about what moved.
  const MAX_ABSORB_WORDS = 1;

  // The cure for the confetti. An equality sandwiched between two edits, that
  // is small relative to BOTH of them, is not a meaningful survival — it is
  // the LCS finding "the", or a single space, in two different sentences.
  // Absorbing it turns shrapnel into phrases.
  //
  // "Relative to BOTH" is load-bearing. Comparing against the larger neighbour
  // alone cascades: every absorption grows the left chunk, which makes the
  // next equality look small by comparison, and one pass swallows the whole
  // paragraph. Requiring the equality to be small against the SMALLER
  // neighbour too — diff-match-patch's semantic-cleanup rule — is what makes
  // the fixpoint stable. tests/diff_engine.test.cjs pins both directions:
  // the confetti must go, and "still open" must survive.
  function absorbTinyEqualities(chunks) {
    let cur = chunks, again = true, guard = 0;
    while (again && guard++ < 20) {
      again = false;
      const out = [];
      for (let i = 0; i < cur.length; i++) {
        const c = cur[i], prev = out[out.length - 1], next = cur[i + 1];
        if (c.t === "eq" && prev && prev.t === "ch" && next && next.t === "ch") {
          const words = c.s.trim() ? c.s.trim().split(/\s+/).length : 0;
          const left = Math.max(prev.del.length, prev.ins.length);
          const right = Math.max(next.del.length, next.ins.length);
          if (words <= MAX_ABSORB_WORDS && c.s.length <= Math.min(left, right)) {
            prev.del += c.s + next.del;
            prev.ins += c.s + next.ins;
            i++;
            again = true;
            continue;
          }
        }
        out.push(c.t === "ch" ? { t: "ch", del: c.del, ins: c.ins } : { t: "eq", s: c.s });
      }
      cur = out;
    }
    return cur;
  }

  function diffChunks(a, b) { return absorbTinyEqualities(toChunks(lcsOps(a, b))); }

  // ── Inline markdown ──────────────────────────────────────────────────────
  // Returns the text as the reader sees it, plus fmt[i] naming the emphasis in
  // force at character i. Both the diff and the renderer read the SAME plain
  // string, so a character offset from one is valid in the other — that is
  // what lets the pane paint insertions onto properly formatted prose instead
  // of onto a stream of asterisks.
  function parseInline(md) {
    const chars = [], fmt = [], stack = [];
    const toggle = (t) => {
      const i = stack.lastIndexOf(t);
      if (i >= 0) stack.splice(i, 1); else stack.push(t);
    };
    let i = 0;
    while (i < md.length) {
      if (md.startsWith("**", i)) { toggle("strong"); i += 2; continue; }
      if (md[i] === "`") { toggle("code"); i++; continue; }
      if (md[i] === "*") { toggle("em"); i++; continue; }
      chars.push(md[i]);
      fmt.push(stack.join("|"));
      i++;
    }
    return { plain: chars.join(""), fmt };
  }

  // ── Structure ────────────────────────────────────────────────────────────
  // Paragraphs and list items. A wrapped list item stays one unit: only a
  // blank line or a new marker starts the next one, so re-flowed markdown does
  // not change the unit count.
  function splitUnits(md) {
    const units = [];
    let buf = [], kind = "p", marker = "";
    const flush = () => {
      if (!buf.length) return;
      const text = buf.join(" ").trim();
      const p = parseInline(text);
      units.push({ kind, marker, text, plain: p.plain, fmt: p.fmt });
      buf = []; kind = "p"; marker = "";
    };
    for (const raw of String(md).replace(/\r/g, "").split("\n")) {
      const line = raw.trim();
      if (!line) { flush(); continue; }
      let m;
      if ((m = line.match(/^(\d+)[.)]\s+(.*)$/))) {
        flush(); kind = "li"; marker = m[1] + "."; buf.push(m[2]); continue;
      }
      if ((m = line.match(/^[-*+]\s+(.*)$/))) {
        flush(); kind = "li"; marker = "•"; buf.push(m[1]); continue;
      }
      buf.push(line);
    }
    flush();
    return units;
  }

  const normKey = (s) => s.toLowerCase().replace(/[^a-z0-9 ]+/g, "").replace(/\s+/g, " ").trim();

  // How likely are these two units the same paragraph, edited?
  //
  // Dice alone is not enough. A list item that answers its own question grows
  // five-fold, and Dice's |A|+|B| denominator punishes that size asymmetry so
  // hard the pair can never clear any useful floor no matter how much of the
  // original survived — which is exactly how three rewritten items ended up
  // rendered twice each, once as a deletion and once as an unrelated
  // insertion. So take the better of Dice and a discounted overlap
  // coefficient, which asks the question that actually matters: how much of
  // the SMALLER side made it into the larger one. The hit floor stops a
  // three-word fragment from scoring 1.0 against any paragraph containing its
  // words.
  const MIN_OVERLAP_HITS = 4;
  const OVERLAP_DISCOUNT = 0.85;
  const SIM_FLOOR = 0.34;
  // A same-numbered list item is the same item. Ordered lists carry their own
  // alignment key, and it beats anything the prose can tell us.
  const MARKER_BONUS = 0.25;

  function similarity(a, b) {
    const A = new Set(normKey(a).split(" ").filter(Boolean));
    const B = new Set(normKey(b).split(" ").filter(Boolean));
    if (!A.size || !B.size) return 0;
    let hit = 0;
    for (const w of A) if (B.has(w)) hit++;
    const dice = (2 * hit) / (A.size + B.size);
    const overlap = hit / Math.min(A.size, B.size);
    return hit >= MIN_OVERLAP_HITS ? Math.max(dice, overlap * OVERLAP_DISCOUNT) : dice;
  }

  // Align two unit lists into rows: same | mod | del | ins.
  function alignUnits(oldU, newU) {
    const A = oldU.map((u) => normKey(u.plain)), B = newU.map((u) => normKey(u.plain));
    const n = A.length, m = B.length;
    const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1
                                 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const raw = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) { raw.push({ t: "same", a: oldU[i++], b: newU[j++] }); }
      else if (dp[i + 1][j] >= dp[i][j + 1]) raw.push({ t: "del", a: oldU[i++] });
      else raw.push({ t: "ins", b: newU[j++] });
    }
    while (i < n) raw.push({ t: "del", a: oldU[i++] });
    while (j < m) raw.push({ t: "ins", b: newU[j++] });

    // Second pass. The exact-text LCS above can only report "identical" or
    // "gone"; a run of deletions immediately followed by insertions is
    // usually one stretch of prose being rewritten, not two unrelated events.
    // Pair them off by similarity, in order — a match that crosses another
    // match is harder to read than no match at all, and genuinely reordered
    // paragraphs are rare enough not to design for.
    const out = [];
    for (let k = 0; k < raw.length; k++) {
      if (raw[k].t !== "del") { out.push(raw[k]); continue; }
      let d = k; while (raw[d] && raw[d].t === "del") d++;
      let s = d; while (raw[s] && raw[s].t === "ins") s++;
      const dels = raw.slice(k, d), inss = raw.slice(d, s);
      if (!inss.length) { out.push.apply(out, dels); k = d - 1; continue; }
      // Walk the deletions in document order and give each the best insertion
      // still available to its right. `floorIdx` is the no-crossing rule: once
      // deletion 2 has taken insertion 3, deletion 3 may only look at 4 and up.
      const usedIns = new Set();
      let floorIdx = 0;
      for (const dr of dels) {
        let best = -1, bestScore = SIM_FLOOR;
        for (let x = floorIdx; x < inss.length; x++) {
          if (usedIns.has(x)) continue;
          let sc = similarity(dr.a.plain, inss[x].b.plain);
          if (dr.a.kind === "li" && inss[x].b.kind === "li" && dr.a.marker === inss[x].b.marker) {
            sc += MARKER_BONUS;
          }
          if (sc > bestScore) { bestScore = sc; best = x; }
        }
        if (best >= 0) {
          usedIns.add(best);
          floorIdx = best + 1;
          out.push({ t: "mod", a: dr.a, b: inss[best].b, sim: bestScore });
        } else out.push(dr);
      }
      // Whatever no deletion claimed is genuinely new text.
      for (let x = 0; x < inss.length; x++) if (!usedIns.has(x)) out.push(inss[x]);
      k = s - 1;
    }
    return out;
  }

  // ── Views ────────────────────────────────────────────────────────────────
  // The renderers return a node TREE, never an HTML string. Block markdown is
  // arbitrary model-and-user text; in this tree a plain string is always a
  // text node when script.js materialises it, so the pane cannot grow an
  // <img onerror> or a <script> out of block content no matter what a block
  // contains. Building strings and setting innerHTML would put that guarantee
  // back in the hands of an escape function nobody re-checks.
  //
  //   vnode := { tag, cls, attrs, kids: [vnode | string] }

  function h(tag, cls, kids, attrs) {
    return { tag, cls: cls || "", attrs: attrs || {}, kids: kids || [] };
  }

  function wrapFormat(text, key) {
    let node = text;
    for (const t of key ? key.split("|") : []) {
      node = h(t === "strong" ? "strong" : t === "em" ? "em" : "code", "", [node]);
    }
    return node;
  }

  // Emit [from,to) of a unit's plain text as kids, restoring its emphasis and
  // wrapping whatever `mark` claims in a single <ins>.
  //
  // The mark is the OUTER grouping and the formatting the inner one,
  // deliberately: group the other way round and a highlighted phrase that
  // contains a bold word breaks into three separate <ins> elements, so one
  // insertion shows a seam at every emphasis boundary and reads as three.
  function runs(plain, fmt, from, to, mark) {
    const out = [];
    let i = from;
    while (i < to) {
      const mk = mark ? mark(i) : "";
      let j = i;
      while (j < to && (mark ? mark(j) : "") === mk) j++;
      const inner = [];
      let k = i;
      while (k < j) {
        const key = fmt[k] || "";
        let l = k;
        while (l < j && (fmt[l] || "") === key) l++;
        inner.push(wrapFormat(plain.slice(k, l), key));
        k = l;
      }
      if (mk) out.push(h("ins", "d-ins", inner));
      else Array.prototype.push.apply(out, inner);
      i = j;
    }
    return out;
  }

  const whole = (u) => runs(u.plain, u.fmt, 0, u.plain.length, null);

  // Where does each chunk land in the NEW text? Insertions get a character
  // range to tint; deletions get an anchor position, since they occupy no
  // space in the new text at all.
  function project(oldPlain, newUnit) {
    const chunks = diffChunks(oldPlain, newUnit.plain);
    const insAt = new Uint8Array(newUnit.plain.length);
    const cuts = [];
    let at = 0;
    for (const c of chunks) {
      if (c.t === "eq") { at += c.s.length; continue; }
      if (c.ins) for (let k = at; k < at + c.ins.length; k++) insAt[k] = 1;
      if (c.del) cuts.push({ at, text: c.del });
      at += c.ins.length;
    }
    return { insAt, cuts, mark: (i) => (insAt[i] ? "ins" : "") };
  }

  // Walk the new text once, splicing each deletion in at its anchor.
  function weave(u, cuts, mark, renderCut) {
    const kids = [];
    let pos = 0, ci = 0;
    while (pos < u.plain.length || ci < cuts.length) {
      const next = ci < cuts.length ? cuts[ci].at : Infinity;
      const stop = Math.min(next, u.plain.length);
      if (stop > pos) {
        Array.prototype.push.apply(kids, runs(u.plain, u.fmt, pos, stop, mark));
        pos = stop;
      }
      if (ci < cuts.length && cuts[ci].at <= pos) { kids.push(renderCut(cuts[ci].text)); ci++; }
      else if (pos >= u.plain.length) break;
    }
    return kids;
  }

  function unitShell(u, kids, cls) {
    if (u.kind === "li") {
      return h("div", "d-li" + (cls ? " " + cls : ""),
        [h("span", "d-marker", [u.marker]), h("span", "d-litext", kids)]);
    }
    return h("p", cls || "", kids);
  }

  // ── Reader ───────────────────────────────────────────────────────────────
  // The new text as prose you can read: structure and emphasis intact,
  // additions tinted, deletions folded into a chip that opens on click. It
  // answers "what does it say now" first and "what moved" second, which is the
  // order a reader actually arrives in.

  function cutChip(text) {
    const t = text.trim();
    const n = t ? t.split(/\s+/).length : 0;
    return h("button", "d-cut", ["⌫ " + n], {
      type: "button",
      "data-cut": t,
      title: t,
      "aria-label": "Show " + n + " removed word" + (n === 1 ? "" : "s"),
    });
  }

  function renderReader(rows) {
    const kids = [];
    for (const r of rows) {
      if (r.t === "del") {
        // A paragraph that is simply gone has no place in the new text to
        // fold into, and it is the one thing a reader most needs told.
        kids.push(h("div", "d-gone", [
          h("span", "d-gone-lab", ["cut entirely"]),
          h("span", "d-gone-txt", whole(r.a)),
        ]));
        continue;
      }
      if (r.t === "same") { kids.push(unitShell(r.b, whole(r.b))); continue; }
      if (r.t === "ins") {
        kids.push(unitShell(r.b, [h("ins", "d-ins", whole(r.b))]));
        continue;
      }
      const p = project(r.a.plain, r.b);
      kids.push(unitShell(r.b, weave(r.b, p.cuts, p.mark, cutChip)));
    }
    return h("div", "d-reader", kids);
  }

  // ── Unified ──────────────────────────────────────────────────────────────
  // Paragraph by paragraph, both sides on show. Word-level marks appear only
  // inside a pair that stayed recognisably the same paragraph; a paragraph
  // rewritten from scratch is one clean removal and one clean addition, which
  // is why the confetti is structurally impossible here.

  function uniRow(cls, gutter, u, kids) {
    const body = u && u.kind === "li"
      ? [h("span", "d-marker", [u.marker])].concat(kids)
      : kids;
    return h("div", "d-row " + cls, [
      h("span", "d-gut", [gutter]),
      h("div", "d-txt", body),
    ]);
  }

  function modKids(a, b) {
    const p = project(a.plain, b);
    return weave(b, p.cuts, p.mark,
      (text) => h("del", "d-cut-text", [text.replace(/\s+$/, "")]));
  }

  function renderUnified(rows) {
    const kids = [];
    let unchanged = [];
    const flushUnchanged = () => {
      if (!unchanged.length) return;
      const n = unchanged.length;
      const body = h("div", "d-fold-body",
        unchanged.map((u) => uniRow("d-same", "·", u, whole(u))), { hidden: "" });
      kids.push(h("button", "d-fold",
        ["… " + n + " unchanged paragraph" + (n > 1 ? "s" : "")],
        { type: "button", "aria-expanded": "false" }));
      kids.push(body);
      unchanged = [];
    };
    for (const r of rows) {
      if (r.t === "same") { unchanged.push(r.b); continue; }
      flushUnchanged();
      if (r.t === "del") kids.push(uniRow("d-del", "−", r.a, whole(r.a)));
      else if (r.t === "ins") kids.push(uniRow("d-ins-row", "+", r.b, whole(r.b)));
      else kids.push(uniRow("d-mod", "≈", r.b, modKids(r.a, r.b)));
    }
    flushUnchanged();
    return h("div", "d-uni", kids);
  }

  return {
    diffChunks, parseInline, splitUnits, alignUnits, similarity,
    renderReader, renderUnified,
    MAX_CELLS, SIM_FLOOR,
  };
});
