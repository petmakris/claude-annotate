#!/usr/bin/env node
/* Folding goes by heading: a heading folds its own part and every untitled
 * part after it, up to the next heading. Run: node skills/annotate/tests/fold_groups.test.cjs */
const path = require("path");
const { foldPlan, ownerOf } = require(path.join(__dirname, "..", "static", "fold-groups.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function eq(a, b, what) {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error((what || "") + " expected " + B + ", got " + A);
}
const sorted = (s) => [...s].sort();

test("a folded heading hides the untitled parts after it", () => {
  const p = foldPlan([
    { id: "a", heading: true, collapsed: true },
    { id: "b", heading: false, collapsed: false },
    { id: "c", heading: false, collapsed: false },
    { id: "d", heading: true, collapsed: false },
    { id: "e", heading: false, collapsed: false },
  ]);
  eq(sorted(p.folded), ["a"]);
  eq(sorted(p.hidden), ["b", "c"]);
});

test("an open heading hides nothing", () => {
  const p = foldPlan([{ id: "a", heading: true, collapsed: false }, { id: "b", heading: false, collapsed: true }]);
  eq(sorted(p.folded), []);
  eq(sorted(p.hidden), []);
});

test("untitled parts before the first heading never fold", () => {
  const p = foldPlan([{ id: "a", heading: false, collapsed: true }, { id: "b", heading: true, collapsed: true }]);
  eq(sorted(p.folded), ["b"]);
  eq(sorted(p.hidden), []);
});

test("a page with no headings folds nothing, whatever an old visit stored", () => {
  const p = foldPlan([{ id: "a", heading: false, collapsed: true }, { id: "b", heading: false, collapsed: true }]);
  eq(sorted(p.folded), []);
  eq(sorted(p.hidden), []);
});

test("a part's fold owner is the heading above it", () => {
  const blocks = [{ id: "x", heading: false }, { id: "a", heading: true }, { id: "b", heading: false }];
  eq(ownerOf(blocks, "b"), "a");
  eq(ownerOf(blocks, "a"), "a");
  eq(ownerOf(blocks, "x"), null);
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
