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

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
