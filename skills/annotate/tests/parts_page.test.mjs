#!/usr/bin/env node
/* Decisions, facts and jobs painted from their spec (static/spec-parts.js), on
 * the shared DOM shim: each decision and job carries its id as
 * data-annotate-id and a comment button, an open decision is marked open, a job
 * says what it waits on, a facts strip is not a comment target, and nothing
 * the spec holds is read as HTML.
 * Run: node skills/annotate/tests/parts_page.test.mjs */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import { install, document } from "../../_shared/tests/dom_shim.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (f) => readFileSync(path.join(here, "..", "static", f), "utf8");
install();
vm.runInThisContext(src("tables.js"));
vm.runInThisContext(src("spec-parts.js"));

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
function paint(painter, spec) {
  const c = document.createElement("div");
  window.AnnotateSpecParts.paint(painter, c, { spec });
  return c;
}

const DEC = (extra) => ({ id: "D1", question: "Q1?", why: "cheap", recommended: "b", status: "open",
  options: [{ id: "a", label: "Alpha", trade: "slow" }, { id: "b", label: "Beta", trade: "fast" }], ...extra });

test("each option is a card, the recommended one marked, each with a Choose button while open", () => {
  const c = paint("decisions", { decisions: [DEC({}), DEC({ id: "D2" })] });
  const d = c.querySelectorAll(".dec");
  eq(d.map((x) => [x.dataset.annotateId, x.dataset.status]), [["D1", "open"], ["D2", "open"]]);
  const o = d[0].querySelectorAll(".dec-opt");
  eq(o.map((x) => x.dataset.option), ["a", "b"]);
  eq(o.map((x) => !!x.dataset.recommended), [false, true]);
  eq(o[1].querySelector(".opt-rec").textContent, "Recommended");
  eq(o[1].querySelector(".dec-why").textContent, "cheap");
  eq(o[0].querySelectorAll(".dec-why").length, 0);
  eq(o.map((x) => x.querySelectorAll("button.dec-choose").length), [1, 1]);
  eq(d[0].querySelectorAll("button.item-comment").length, 1);
  eq(o[0].querySelector(".dec-choose").getAttribute("aria-label"), "Choose a: Alpha");
  eq(o[0].querySelector(".dec-choose").textContent, "", "its words come from CSS");
});

test("an answered decision marks the choice, dims the rest, and has no Choose buttons", () => {
  const c = paint("decisions", { decisions: [DEC({ status: "answered", chosen: "a", answer: "A, but small" })] });
  const o = c.querySelectorAll(".dec-opt");
  eq(o.map((x) => [!!x.dataset.chosen, !!x.dataset.dim]), [[true, false], [false, true]]);
  eq(o[0].querySelector(".opt-mine").textContent, "Your choice");
  eq(c.querySelectorAll("button.dec-choose").length, 0);
  eq(c.querySelector(".dec-ans").textContent, "Your answer A, but small");
});

test("pressing Choose pins `Choose <id>: <label>` on that decision", () => {
  const pinned = [];
  window.AnnotateSubunits = { pinComment: (a) => pinned.push(a) };
  const section = document.createElement("section");
  section.className = "block"; section.dataset.blockId = "section-3";
  const content = document.createElement("div");
  window.AnnotateSpecParts.paint("decisions", content, { spec: { decisions: [DEC({})] } });
  section.append(content); document.body.append(section);
  content.querySelectorAll(".dec-opt")[1].querySelector("button.dec-choose").click();
  eq(pinned, [{ block_id: "section-3", step_id: "D1", text: "Choose b: Beta" }]);
});

test("each job is a comment target and says what it waits on", () => {
  const c = paint("jobs", { jobs: [
    { id: "J1", title: "A", does: "does a", after: [], status: "done" },
    { id: "J2", title: "B", does: "does b", after: ["J1"], status: "blocked" },
    { id: "J3", title: "C", does: "does c", after: ["J1", "J2"], status: "todo" }] });
  const j = c.querySelectorAll(".job");
  eq(j.map((x) => x.dataset.annotateId), ["J1", "J2", "J3"]);
  eq(j.map((x) => x.querySelector(".job-after").textContent), ["Starts first", "Waits on J1", "Waits on J1, J2"]);
  eq(j.map((x) => x.querySelector(".job-status").textContent), ["done", "blocked", "todo"]);
});

test("a facts strip is not a comment target", () => {
  const c = paint("facts", { facts: [{ value: "3 files", label: "change" }, { value: "2 days", label: "estimate" }] });
  eq(c.querySelectorAll(".fact").length, 2);
  eq(c.querySelector(".fact-value").textContent, "3 files");
  eq(c.querySelectorAll("[data-annotate-id]").length, 0);
  eq(c.querySelectorAll("button").length, 0);
});

test("spec words are text, never HTML", () => {
  const c = paint("facts", { facts: [{ value: "<b>x</b>", label: "<i>y</i>" }, { value: "2", label: "z" }] });
  eq(c.querySelectorAll("b").length, 0);
  eq(c.querySelector(".fact-value").textContent, "<b>x</b>");
});

process.stdout.write(`${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
