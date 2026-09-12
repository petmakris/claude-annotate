#!/usr/bin/env node
/*
 * Behavioural tests for the card-title rule (static/block-title.js).
 *
 * A source-string check cannot tell "flowchart falls through to the markdown
 * branch" from "flowchart has its own branch": both contain the word
 * flowchart. The rule is a pure function of one block, so it is executed here
 * and asserted on its output.
 *
 * The defect that made this file exist: a flowchart carries a real
 * `spec.title` — "Outbound: every id montblanc puts on the wire" — and the
 * card header showed "Section", because only `sequence` and `choice` had a
 * spec fallback and a flowchart has no `markdown` for the last branch to read.
 * With one diagram per dimension of a topic, that is a whole page of cards
 * called "Section".
 *
 * Run:  node skills/annotate/tests/block_title.test.cjs
 */
const path = require("path");
const { blockTitle } = require(path.join(__dirname, "..", "static", "block-title.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function eq(actual, expected, what) {
  if (actual !== expected)
    throw new Error((what || "") + " expected " + JSON.stringify(expected) +
                    ", got " + JSON.stringify(actual));
}

test("a flowchart is named by its spec title", () => {
  eq(blockTitle({
    id: "section-4", kind: "flowchart",
    spec: { title: "Outbound: every id montblanc puts on the wire", nodes: [], edges: [] },
  }), "Outbound: every id montblanc puts on the wire");
});

test("four flowcharts on one page get four different names", () => {
  const titles = [
    "Outbound: every id montblanc puts on the wire",
    "Inbound, proposal level: where each response field lands",
    "Inbound, order level: the same split, plus the correlation",
    "Two readers, one column — resolved branch in bold",
  ].map((t) => blockTitle({ id: "x", kind: "flowchart", spec: { title: t } }));
  eq(new Set(titles).size, 4, "distinct titles");
  eq(titles.includes("Section"), false, "no card fell back to Section");
});

test("an explicit block title still wins over the spec title", () => {
  eq(blockTitle({
    kind: "flowchart", title: "Author's own name",
    spec: { title: "the spec name" },
  }), "Author's own name");
});

test("a flowchart with no title of any kind says Diagram, never Section", () => {
  eq(blockTitle({ kind: "flowchart", spec: { nodes: [], edges: [] } }), "Diagram");
  eq(blockTitle({ kind: "flowchart" }), "Diagram");
});

test("a blank or whitespace spec title is not a title", () => {
  eq(blockTitle({ kind: "flowchart", spec: { title: "   " } }), "Diagram");
});

test("sequence keeps the spec fallback it already had", () => {
  eq(blockTitle({ kind: "sequence", spec: { title: "One save, end to end" } }),
     "One save, end to end");
  eq(blockTitle({ kind: "sequence", spec: {} }), "Diagram");
});

test("choice keeps its question", () => {
  eq(blockTitle({ kind: "choice", spec: { question: "How do we close the id question?" } }),
     "How do we close the id question?");
  eq(blockTitle({ kind: "choice", spec: {} }), "Decision");
});

test("markdown still takes its first heading", () => {
  eq(blockTitle({ kind: "markdown", markdown: "## Two identities, one column\n\nbody" }),
     "Two identities, one column");
  eq(blockTitle({ kind: "markdown", markdown: "plain first line\n\nmore" }), "plain first line");
  eq(blockTitle({ kind: "markdown", markdown: "" }), "Section");
});

test("a long markdown title is still elided at 60 characters", () => {
  const long = "x".repeat(80);
  const out = blockTitle({ kind: "markdown", markdown: "# " + long });
  eq(out.length, 60, "elided length");
  eq(out.endsWith("…"), true, "ellipsis");
});

test("a title is trimmed of markdown emphasis", () => {
  eq(blockTitle({ kind: "markdown", markdown: "# **Correction** — the `nightly` step" }),
     "Correction — the nightly step");
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
