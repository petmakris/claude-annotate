#!/usr/bin/env node
/*
 * Behavioural tests for the per-block diff engine (static/diff.js).
 *
 * These are NOT source-string smoke tests. The engine is a pure function of
 * two strings, so it can be executed directly and asserted on its output —
 * which is the only kind of test that can catch an alignment or cleanup
 * regression. A grep for "wordDiff" proves nothing about whether the pane
 * shreds a rewritten paragraph into confetti.
 *
 * Run:  node skills/annotate/tests/diff_engine.test.cjs
 * (also run by pytest via test_diff_engine.py, which skips if node is absent)
 */
const path = require("path");
const D = require(path.join(__dirname, "..", "static", "diff.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function eq(actual, expected, what) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error((what || "") + " expected " + b + ", got " + a);
}
function ok(cond, msg) { if (!cond) throw new Error(msg); }

const changes = (chunks) => chunks.filter((c) => c.t === "ch");
const kinds = (rows) => rows.map((r) => r.t).join(" ");

/* ── The confetti ─────────────────────────────────────────────────────────
   The defect in the shipped pane: a rewritten sentence comes out as a long
   alternation of one-word edits, because the LCS anchors on stopwords that
   appear in both versions and threads them through the result. */

const SHRED_OLD = "That single sentence hides three separate decisions:";
const SHRED_NEW = "That sentence hid three decisions. Two are now settled:";

/* A real rewrite from the case that prompted this work. Diffed naively it
   comes out as eight edits held apart by equalities that are, four times over,
   a single space character. */
const REWRITE_OLD =
  "Which proposals get swept? Everything still open, or only the ones an advisor built by hand?";
const REWRITE_NEW =
  "Which proposals are settled: everything still open, regardless of whether an advisor " +
  "built it by hand or a campaign generated it. Narrow it later only if a real " +
  "performance problem shows up.";

const sandwichedEqualities = (chunks) => chunks.filter(
  (c, i) => c.t === "eq" && chunks[i - 1] && chunks[i - 1].t === "ch"
                         && chunks[i + 1] && chunks[i + 1].t === "ch");

test("a rewritten sentence yields phrase-sized edits, not one-word confetti", () => {
  const c = changes(D.diffChunks(REWRITE_OLD, REWRITE_NEW));
  ok(c.length <= 4, "expected at most 4 edits, got " + c.length +
     ": " + JSON.stringify(c.map((x) => x.del.trim() + " -> " + x.ins.trim())));
});

test("two edits are never held apart by nothing but whitespace", () => {
  const gaps = sandwichedEqualities(D.diffChunks(REWRITE_OLD, REWRITE_NEW))
    .filter((c) => !c.s.trim());
  eq(gaps.length, 0, "edits split by a whitespace-only equality:");
});

test("no bare stopword is left standing between two edits", () => {
  const STOP = new Set(["the", "is", "a", "of", "and", "to", "it", "in", "that", "on", "by", "or"]);
  for (const c of sandwichedEqualities(D.diffChunks(REWRITE_OLD, REWRITE_NEW))) {
    ok(!STOP.has(c.s.trim().toLowerCase()),
       "stopword " + JSON.stringify(c.s.trim()) + " left standing between two edits");
  }
});

test("cleanup does not run away and swallow real survivals", () => {
  /* Testing an equality against only the LARGER neighbouring edit cascades:
     each absorption grows the left chunk, so the next equality looks small by
     comparison and the pass eats the whole paragraph. Genuine survivals — a
     phrase that is word-for-word identical in both versions — must survive. */
  const kept = D.diffChunks(REWRITE_OLD, REWRITE_NEW)
    .filter((c) => c.t === "eq").map((c) => c.s).join("");
  ok(/still open/.test(kept), "'still open' is unchanged in both versions but was absorbed");
  ok(/advisor built/.test(kept), "'advisor built' is unchanged in both versions but was absorbed");
  const shortKept = D.diffChunks(SHRED_OLD, SHRED_NEW)
    .filter((c) => c.t === "eq").map((c) => c.s).join("");
  ok(/sentence/.test(shortKept), "the word 'sentence' is unchanged but was absorbed into an edit");
  ok(/three/.test(shortKept), "the word 'three' is unchanged but was absorbed into an edit");
});

test("an unchanged string produces no edits at all", () => {
  eq(changes(D.diffChunks("same text here", "same text here")).length, 0);
});

test("chunks reassemble into both inputs exactly", () => {
  const a = "If a proposal fails the run stops and the rest are left untouched.";
  const b = "If a proposal fails the run stops, and every proposal after it keeps its status.";
  const chunks = D.diffChunks(a, b);
  const back = (side) => chunks.map((c) => c.t === "eq" ? c.s : c[side]).join("");
  eq(back("del"), a, "deletion side does not reassemble to the old text:");
  eq(back("ins"), b, "insertion side does not reassemble to the new text:");
});

/* ── Markdown must not leak into the diff ─────────────────────────────────
   The shipped pane diffs blk.markdown, so `**bold**` and list markers become
   diffable tokens and the pane shows punctuation the card never renders. */

test("emphasis markers are not diffable tokens", () => {
  const before = D.parseInline("That **single** sentence.").plain;
  const after = D.parseInline("That sentence.").plain;
  const c = changes(D.diffChunks(before, after));
  const text = c.map((x) => x.del + x.ins).join("");
  ok(!text.includes("*"), "asterisks reached the diff: " + JSON.stringify(text));
});

test("parseInline reports where the emphasis was, by character", () => {
  const { plain, fmt } = D.parseInline("a **b** `c`");
  eq(plain, "a b c");
  eq(fmt[0], "", "plain char carries no format");
  eq(fmt[2], "strong", "the bold char is not marked strong");
  eq(fmt[4], "code", "the code char is not marked code");
});

/* ── Structure before words ───────────────────────────────────────────────
   The shipped pane emits one <p>, so paragraphs and lists flatten. */

test("splitUnits keeps paragraphs and numbered items apart", () => {
  const u = D.splitUnits("First para.\n\n1. Item one\n\n2. Item two\n\nLast para.");
  eq(u.map((x) => x.kind), ["p", "li", "li", "p"]);
  eq(u.map((x) => x.marker), ["", "1.", "2.", ""]);
  eq(u[1].plain, "Item one");
});

test("a wrapped list item stays one unit", () => {
  const u = D.splitUnits("1. Item one\n   continued here\n\n2. Item two");
  eq(u.length, 2);
  eq(u[0].plain, "Item one continued here");
});

/* ── Alignment ────────────────────────────────────────────────────────────
   The case the whole redesign exists for: a list item that answers its own
   question grows several-fold. Dice similarity cannot pair it — its |A|+|B|
   denominator punishes the size asymmetry — so the item falls through as an
   unrelated delete plus insert and the pane shows it twice. */

const ITEM_OLD = [
  "The ticket says the checks must run once a day.",
  "",
  "1. **Which batch?** The requirement names one without saying which.",
  "",
  "2. **Which proposals get swept?** Everything still open, or only the ones an advisor built by hand?",
  "",
  "Everything below is read from the code, not assumed.",
].join("\n");

const ITEM_NEW = [
  "The ticket says the checks must run once a day.",
  "",
  "1. **Which batch — settled.** It is the nightly batch, which does exist in the application under that name: an ordered list of housekeeping steps that reloads portfolio data, re-prices every open proposal and expires stale ones. The sweep becomes one more step in that list.",
  "",
  "2. **Which proposals — settled: everything still open**, regardless of whether an advisor built it by hand or a campaign generated it. Narrow it later only if a real performance problem shows up.",
].join("\n");

test("a list item that grew five-fold still pairs with its original", () => {
  const rows = D.alignUnits(D.splitUnits(ITEM_OLD), D.splitUnits(ITEM_NEW));
  eq(kinds(rows), "same mod mod del",
     "alignment wrong — a grown item was not recognised as a rewrite of its original:");
});

test("an untouched paragraph aligns as unchanged", () => {
  const rows = D.alignUnits(D.splitUnits(ITEM_OLD), D.splitUnits(ITEM_NEW));
  eq(rows[0].t, "same");
  eq(rows[0].b.plain, "The ticket says the checks must run once a day.");
});

test("a paragraph with no counterpart is a deletion, not a bad pairing", () => {
  const rows = D.alignUnits(D.splitUnits(ITEM_OLD), D.splitUnits(ITEM_NEW));
  const last = rows[rows.length - 1];
  eq(last.t, "del");
  ok(/read from the code/.test(last.a.plain), "the wrong unit was reported deleted");
});

test("matched pairs never cross each other", () => {
  const rows = D.alignUnits(D.splitUnits(ITEM_OLD), D.splitUnits(ITEM_NEW));
  let lastNew = -1;
  for (const r of rows) {
    if (r.t !== "same" && r.t !== "mod") continue;
    const idx = D.splitUnits(ITEM_NEW).findIndex((u) => u.plain === r.b.plain);
    ok(idx > lastNew, "pairing crosses: new unit " + idx + " came after " + lastNew);
    lastNew = idx;
  }
});

test("an unrelated paragraph is not force-paired with a survivor", () => {
  const oldU = D.splitUnits("The provider is rate limited to forty calls a second.");
  const newU = D.splitUnits("Advisors see nothing different on the proposal screen.");
  eq(kinds(D.alignUnits(oldU, newU)), "del ins");
});

test("a compact keeps every dropped paragraph visible as a deletion", () => {
  const before = ["Para one about rate limits.", "", "Para two about volumes.", "",
                  "Para three about failures.", "", "Para four about the stop rule."].join("\n");
  const after = "Para four about the stop rule.";
  const rows = D.alignUnits(D.splitUnits(before), D.splitUnits(after));
  eq(rows.filter((r) => r.t === "del").length, 3, "dropped paragraphs went missing:");
  eq(rows.filter((r) => r.t === "same").length, 1);
});

/* ── The cell cap the shipped engine already had ─────────────────────────── */

test("an oversized pair falls back instead of allocating a huge table", () => {
  const big = new Array(2000).fill("word").join(" ");
  const other = new Array(2000).fill("term").join(" ");
  const chunks = D.diffChunks(big, other);
  eq(changes(chunks).length, 1, "expected one wholesale replacement:");
  eq(chunks[0].del, big);
  eq(chunks[0].ins, other);
});

/* ══ View renderers ══════════════════════════════════════════════════════
   The renderers return a node TREE, not an HTML string. Block markdown is
   arbitrary model-and-user text, so a string kid in this tree always becomes
   a text node when script.js materialises it — the pane cannot grow a <script>
   or an onerror handler even if a block contains one. Returning a tree also
   makes the layout assertable here instead of only in a browser.

   vnode := { tag, cls?, attrs?, kids: [vnode | string] } */

const HOSTILE = '<img src=x onerror="alert(1)"> and <script>bad()</script>';

function walk(node, fn) {
  if (typeof node === "string") { fn(node); return; }
  fn(node);
  for (const k of node.kids || []) walk(k, fn);
}
function collectText(node) {
  const out = [];
  walk(node, (n) => { if (typeof n === "string") out.push(n); });
  return out.join("");
}
function tagsOf(node) {
  const out = [];
  walk(node, (n) => { if (typeof n !== "string" && n.tag) out.push(n.tag); });
  return out;
}
function findAll(node, cls) {
  const out = [];
  walk(node, (n) => { if (typeof n !== "string" && (n.cls || "").split(" ").includes(cls)) out.push(n); });
  return out;
}

const rowsFor = (before, after) => D.alignUnits(D.splitUnits(before), D.splitUnits(after));

/* ── Reader ─────────────────────────────────────────────────────────────── */

test("reader renders the new text, not the old", () => {
  const tree = D.renderReader(rowsFor("The run stops there.", "The run halts there."));
  const text = collectText(tree);
  ok(text.includes("halts"), "the new wording is missing: " + JSON.stringify(text));
  ok(!text.includes("stops"), "the old wording is shown inline: " + JSON.stringify(text));
});

test("reader marks an addition as an insertion", () => {
  const tree = D.renderReader(rowsFor("The run stops.", "The run stops immediately."));
  const ins = findAll(tree, "d-ins");
  ok(ins.length >= 1, "no insertion was marked");
  ok(/immediately/.test(collectText(ins[0])), "the wrong span was marked as added");
});

test("reader folds a deletion into a chip that carries the cut text", () => {
  const tree = D.renderReader(rowsFor("The run stops there quickly.", "The run stops there."));
  const cuts = findAll(tree, "d-cut");
  eq(cuts.length, 1, "expected exactly one cut chip:");
  ok(/quickly/.test(cuts[0].attrs["data-cut"]), "the chip does not carry what was cut");
  eq(cuts[0].tag, "button", "the chip must be focusable to be openable by keyboard");
});

test("reader keeps a wholly removed paragraph visible", () => {
  const tree = D.renderReader(rowsFor("Kept para.\n\nDropped para about limits.", "Kept para."));
  const gone = findAll(tree, "d-gone");
  eq(gone.length, 1, "a dropped paragraph vanished from the pane:");
  ok(/Dropped para about limits/.test(collectText(gone[0])));
});

test("reader preserves bold inside an unchanged run", () => {
  const tree = D.renderReader(rowsFor("It is the **nightly** batch.", "It is the **nightly** run."));
  ok(tagsOf(tree).includes("strong"), "emphasis was flattened away");
  ok(!collectText(tree).includes("*"), "asterisks leaked into the rendered text");
});

test("reader keeps a list item's marker", () => {
  const tree = D.renderReader(rowsFor("1. First thing here.", "1. First item here."));
  ok(collectText(tree).includes("1."), "the list marker was dropped");
});

/* ── Unified ────────────────────────────────────────────────────────────── */

test("unified shows a rewritten paragraph once, with both sides", () => {
  const tree = D.renderUnified(rowsFor("The run stops there.", "The run halts there."));
  const mod = findAll(tree, "d-mod");
  eq(mod.length, 1, "expected one modified row:");
  const text = collectText(mod[0]);
  ok(/stops/.test(text) && /halts/.test(text), "a modified row must show what went and what came: " + text);
});

test("unified collapses a run of unchanged paragraphs behind a control", () => {
  const before = "One stays.\n\nTwo stays.\n\nThree changes here.";
  const after = "One stays.\n\nTwo stays.\n\nThree is different now.";
  const tree = D.renderUnified(rowsFor(before, after));
  const folds = findAll(tree, "d-fold");
  eq(folds.length, 1, "unchanged paragraphs were not collapsed:");
  eq(folds[0].tag, "button");
  ok(/2 unchanged/.test(collectText(folds[0])), "the fold does not say how many it hides");
});

test("unified does not collapse when nothing is unchanged", () => {
  const tree = D.renderUnified(rowsFor("Only para here.", "Wholly different text now."));
  eq(findAll(tree, "d-fold").length, 0);
});

test("unified marks a deleted paragraph and an added one distinctly", () => {
  const tree = D.renderUnified(rowsFor("Gone entirely from here.", "Arrived fresh in this spot."));
  eq(findAll(tree, "d-del").length, 1, "no deletion row:");
  eq(findAll(tree, "d-ins-row").length, 1, "no insertion row:");
});

/* ── Safety ─────────────────────────────────────────────────────────────── */

for (const [name, render] of [["reader", "renderReader"], ["unified", "renderUnified"]]) {
  test(name + " never turns block markup into nodes", () => {
    const tree = D[render](rowsFor("Was plain before.", HOSTILE));
    const tags = tagsOf(tree);
    ok(!tags.includes("img"), "an <img> was materialised from block text");
    ok(!tags.includes("script"), "a <script> was materialised from block text");
    walk(tree, (n) => {
      if (typeof n === "string") return;
      for (const k of Object.keys(n.attrs || {})) {
        ok(!/^on/i.test(k), "an event-handler attribute reached the tree: " + k);
      }
    });
    ok(collectText(tree).includes("onerror"), "the hostile text should survive as literal text");
  });
}

process.stdout.write("\n" + (ran - failures) + "/" + ran + " passed\n");
process.exit(failures ? 1 : 0);
