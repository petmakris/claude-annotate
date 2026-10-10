#!/usr/bin/env node
/* A comment may cover the end of one part and the start of the next.
 * Run: node skills/annotate/tests/spans.test.cjs */
const path = require("path");
const S = require(path.join(__dirname, "..", "static", "spans.js"));

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
const a = { block_id: "section-10", selected_text: "never with a Jira token.", prefix: "flow, ", suffix: "" };
const b = { block_id: "section-1", selected_text: "Nomad publishes every change", prefix: "", suffix: " to a job" };

test("one part keeps today's key and shape", () => {
  eq(S.markKey([a]), "section-10::__span__::flow, ␟never with a Jira token.␟");
  eq(S.withSpans([a]), a);
  eq(S.partsOf(a), [a]);
});

test("two parts make one mark that names both blocks", () => {
  const m = S.withSpans([a, b]);
  eq(m.block_id, "section-10");
  eq(m.selected_text, "never with a Jira token.\nNomad publishes every change");
  eq(m.spans, [a, b]);
  eq(S.blockIdsOf(m), ["section-10", "section-1"]);
  eq(S.partsOf(m), [a, b]);
});

test("the key of a two-part mark differs from either part's", () => {
  const k = S.markKey([a, b]);
  eq(k === S.markKey([a]) || k === S.markKey([b]), false);
});

test("a picture or a question between the words is left out", () => {
  const pic = { block_id: "section-2", selected_text: "ON START", prefix: "", suffix: "" };
  const kinds = { "section-10": "markdown", "section-2": "sequence", "section-1": "markdown" };
  eq(S.textOnly([a, pic, b], (id) => kinds[id], ["choice", "sequence", "diagram", "flowchart"]), [a, b]);
});

// Parts as overlapping() hands them over: found on the page, [start, end).
const at = (block_id, start, end) => ({ block_id, span: [start, end] });

test("overlapping words in the same part overlap", () => {
  eq(S.overlaps([at("section-1", 10, 30)], [at("section-1", 25, 40)]), true);
  eq(S.overlaps([at("section-1", 10, 30)], [at("section-1", 12, 20)]), true);
});

test("the same offsets in different parts do not overlap", () => {
  eq(S.overlaps([at("section-1", 10, 30)], [at("section-2", 10, 30)]), false);
});

test("a two-part mark overlaps a one-part anchor on either of its parts", () => {
  const mark = [at("section-1", 80, 120), at("section-2", 0, 15)];
  eq(S.overlaps(mark, [at("section-1", 100, 110)]), true);
  eq(S.overlaps(mark, [at("section-2", 5, 9)]), true);
  eq(S.overlaps([at("section-2", 5, 9)], mark), true);
  eq(S.overlaps(mark, [at("section-3", 5, 9)]), false);
});

test("ranges that only touch do not overlap", () => {
  eq(S.overlaps([at("section-1", 10, 30)], [at("section-1", 30, 40)]), false);
  eq(S.overlaps([at("section-1", 30, 40)], [at("section-1", 10, 30)]), false);
});

test("a part whose words are gone overlaps nothing", () => {
  eq(S.overlaps([{ block_id: "section-1", span: null }], [at("section-1", 0, 99)]), false);
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
