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

test("each decision is a comment target with its status and a button", () => {
  const c = paint("decisions", { decisions: [
    { id: "D1", question: "Q1?", recommendation: "Yes", why: "cheap", status: "open" },
    { id: "D2", question: "Q2?", recommendation: "No", why: "slow", status: "answered", answer: "Fine" }] });
  const d = c.querySelectorAll(".dec");
  eq(d.map((x) => [x.dataset.annotateId, x.dataset.status]), [["D1", "open"], ["D2", "answered"]]);
  eq(d.map((x) => x.querySelectorAll("button.item-comment").length), [1, 1]);
  eq(d[0].querySelectorAll(".dec-ans").length, 0);
  eq(d[1].querySelector(".dec-ans").textContent, "Your answer Fine");
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
