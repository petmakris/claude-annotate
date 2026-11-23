#!/usr/bin/env node
/* Table rows as comment targets (static/tables.js), on the shared DOM shim:
 * each body row gets an id from its first cell, ids are unique within a part,
 * an empty first cell falls back to row-N, a header row gets none, and the
 * comment button holds no text (so it never enters a part's text offsets).
 * Run: node skills/annotate/tests/tables_page.test.mjs */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import { install, document } from "../../_shared/tests/dom_shim.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
install();
vm.runInThisContext(readFileSync(path.join(here, "..", "static", "tables.js"), "utf8"));

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
function part(html) {
  const div = document.createElement("div");
  div.innerHTML = html;
  window.AnnotateTables.decorate(div);
  return div;
}
const ids = (div) => [...div.querySelectorAll("tbody tr")].map((tr) => tr.dataset.annotateId);

test("a body row's id is its first cell, slugged", () => {
  const d = part("<table><thead><tr><th>Option</th><th>Cost</th></tr></thead><tbody>"
    + "<tr><td>Use Redis (cached)</td><td>2</td></tr><tr><td>Plain SQL!</td><td>1</td></tr></tbody></table>");
  eq(ids(d), ["use-redis-cached", "plain-sql"]);
});

test("a repeated first cell gets a suffix, an empty one row-N", () => {
  const d = part("<table><tbody><tr><td>A</td><td>1</td></tr><tr><td>A</td><td>2</td></tr>"
    + "<tr><td></td><td>3</td></tr></tbody></table>");
  eq(ids(d), ["a", "a-2", "row-3"]);
});

test("the header row is not a target", () => {
  const d = part("<table><thead><tr><th>H</th></tr></thead><tbody><tr><td>x</td></tr></tbody></table>");
  eq(d.querySelectorAll("thead tr")[0].dataset.annotateId, undefined);
});

test("each row gets one comment button with no text in it", () => {
  const d = part("<table><tbody><tr><td>x</td><td>y</td></tr></tbody></table>");
  const b = d.querySelectorAll(".row-comment");
  eq(b.length, 1);
  eq(b[0].textContent, "");
  window.AnnotateTables.decorate(d);
  eq(d.querySelectorAll(".row-comment").length, 1, "decorating again adds none");
});

test("an authored id on a row is kept", () => {
  const d = part('<table><tbody><tr data-annotate-id="mine"><td>x</td></tr></tbody></table>');
  eq(ids(d), ["mine"]);
});

process.stdout.write(`${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
