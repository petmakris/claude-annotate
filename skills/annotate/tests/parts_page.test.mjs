#!/usr/bin/env node
/* Decisions, facts and jobs painted from their spec (static/spec-parts.js), on
 * the shared DOM shim. Decisions: hard questions first, one filled button per
 * open card, a pick pins exactly `Choose <id>: <label>` as a pending comment on
 * that decision, the reader's own words pin as they wrote them, what a card
 * shows is worked out from the pending comment and the page's busy state, and
 * nothing is pinned unless a button was pressed. Jobs and facts as before.
 * Run: node skills/annotate/tests/parts_page.test.mjs */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import { install, document, ShimEvent } from "../../_shared/tests/dom_shim.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (f) => readFileSync(path.join(here, "..", "static", f), "utf8");
install();
vm.runInThisContext(src("tables.js"));

// What the page's round holds, as AnnotateSubunits shows it to the painter.
const marks = new Map();
const pinned = [];
const removed = [];
window.AnnotateSubunits = {
  stepMark: (b, s) => marks.get(b + "|" + s) || null,
  // As the engine does after a change: tell the page the pending marks changed.
  pinComment: (a) => { pinned.push(a); marks.set(a.block_id + "|" + a.step_id, { kind: "comment", text: a.text }); document.dispatchEvent(new ShimEvent("annotate:marks")); },
  removeStepMark: (b, s) => { removed.push([b, s]); marks.delete(b + "|" + s); document.dispatchEvent(new ShimEvent("annotate:marks")); },
};
vm.runInThisContext(src("spec-parts.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  marks.clear(); pinned.length = 0; removed.length = 0;
  document.body.classList.remove("is-busy");
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
let n = 0;
// A decisions part inside a section on the page, as createBlockSection leaves it.
function mount(decs) {
  const section = document.createElement("section");
  section.className = "block"; section.dataset.blockId = "section-" + (++n);
  const content = document.createElement("div");
  window.AnnotateSpecParts.paint("decisions", content, { id: section.dataset.blockId, spec: { decisions: decs } });
  section.append(content); document.body.append(section);
  return { section, content, id: section.dataset.blockId };
}
const press = (root, text, nth = 0) => {
  const b = root.querySelectorAll("button").filter((x) => x.textContent === text)[nth];
  if (!b) throw new Error("no button " + text);
  b.click();
};
const buttons = (root) => root.querySelectorAll("button").map((b) => b.textContent);
const opt = (id, label, gain, cost, extra) => ({ id, label, gain, cost, ...extra });
const DEC = (id, change, extra) => ({
  id, question: "Question " + id + "?", change, why: "because", recommended: "a", status: "open", next: "Claude builds it.",
  ...(change === "hard" ? { change_note: "Undoing it costs a week." } : {}),
  options: [opt("a", "Label A " + id, "gets A", "costs A", { detail: "tech A" }), opt("b", "Label B " + id, "gets B", "costs B")],
  ...extra,
});
const SEVEN = ["easy", "hard", "easy", "easy", "hard", "easy", "easy"].map((c, i) => DEC("D" + (i + 1), c));

test("hard questions come first, grouped and counted, with a summary and one chip each", () => {
  const { content } = mount(SEVEN);
  eq(content.querySelectorAll(".dec").map((d) => d.dataset.annotateId), ["D2", "D5", "D1", "D3", "D4", "D6", "D7"]);
  eq(content.querySelectorAll(".dec-group").map((g) => g.textContent),
     ["Read these first. Hard to undo (2)", "Easy to change later. A wrong pick costs little (5)"]);
  eq(content.querySelector(".dec-sum-count").textContent, "0 of 7 answered");
  eq(content.querySelector(".dec-sum-sub").textContent, "7 not decided. Tap a number to jump to that question.");
  eq(content.querySelectorAll(".dec-nchip").map((c) => [c.textContent, c.dataset.hard]),
     [["1", "1"], ["2", "1"], ["3", "0"], ["4", "0"], ["5", "0"], ["6", "0"], ["7", "0"]]);
  eq(content.querySelectorAll(".dec-no").map((x) => x.textContent).slice(0, 3), ["Question 1", "Question 2", "Question 3"]);
});

test("an open card has one filled button, the exact button texts and one Other way line", () => {
  const { content } = mount(SEVEN);
  const d = content.querySelectorAll(".dec")[0];
  eq(d.querySelectorAll(".dec-btn.pri").length, 1);
  eq(d.querySelector(".dec-btn.pri").textContent, "Go with Claude's suggestion");
  eq(d.querySelectorAll("button").filter((b) => b.className.includes("dec-btn")).map((b) => b.textContent),
     ["Go with Claude's suggestion", "See other way", "Write my own"]);
  eq(d.querySelectorAll(".dec-oth").map((o) => o.textContent), ["Other wayLabel B D2"]);
  eq(d.querySelector(".dec-hard").textContent, "Undoing it costs a week.");
  eq(d.querySelector(".dec-chip").textContent, "Hard to undo");
  eq(d.querySelector(".dec-next").textContent, "After you send: Claude builds it.");
  eq(content.querySelectorAll(".dec-btn.pri").length, 7);
});

test("a decision written with only trade still renders", () => {
  const old = { id: "D1", question: "Q?", why: "w", recommended: "a", status: "open",
    options: [{ id: "a", label: "Alpha", trade: "slow but safe" }, { id: "b", label: "Beta", trade: "fast" }] };
  const { content } = mount([old]);
  eq(content.querySelector(".dec-trade").textContent, "slow but safe");
  eq(content.querySelectorAll(".dec-sum").length, 0, "one decision has no strip");
  eq(content.querySelectorAll(".dec-group").length, 0);
  eq(content.querySelectorAll(".dec-no").length, 0);
  eq(content.querySelector(".dec-btn.pri").textContent, "Go with Claude's suggestion");
});

test("going with the suggestion pins exactly `Choose a: <label>`, and See other way shows each alternative", () => {
  const { content, id } = mount([DEC("D1", "easy", { switch_if: "You like B." })]);
  press(content, "Go with Claude's suggestion");
  eq(pinned, [{ block_id: id, step_id: "D1", text: "Choose a: Label A D1" }]);
  eq(content.querySelector(".dec").dataset.status, "picked");
  eq(content.querySelector(".dec-state").textContent, "Picked, not sent");
  eq(content.querySelector(".dec-mine").textContent, "Your pick: Label A D1This is Claude's suggestion.");
  eq(content.querySelectorAll(".dec-nchip").length, 0, "one decision: no chips");
  pinned.length = 0; marks.clear();
  // a second part: the alternative path
  const two = mount([DEC("D1", "easy", { switch_if: "You like B." })]);
  press(two.content, "See other way");
  eq(two.content.querySelector(".dec-if").textContent, "Pick this way if: You like B.");
  press(two.content, "Pick this one instead");
  eq(pinned, [{ block_id: two.id, step_id: "D1", text: "Choose b: Label B D1" }]);
  eq(two.content.querySelector(".dec-mine small").textContent, 'Not Claude\'s suggestion. Claude suggested "Label A D1".');
});

test("Use my answer pins the words as written, with no prefix; empty pins nothing", () => {
  const { content, id } = mount([DEC("D1", "easy")]);
  press(content, "Write my own");
  press(content, "Use my answer");
  eq(pinned, [], "empty text pins nothing");
  content.querySelector("textarea").value = "  Both, A first  ";
  content.querySelector("textarea").dispatchEvent(new window.Event("input"));
  press(content, "Use my answer");
  eq(pinned, [{ block_id: id, step_id: "D1", text: "Both, A first" }]);
  eq(content.querySelector(".dec-mine").textContent, "Your own words: Both, A first");
});

test("silence: painting, opening and closing things pins nothing, and nothing is answered", () => {
  const { content } = mount(SEVEN);
  press(content, "See other way"); press(content, "Hide the other way"); press(content, "Write my own");
  eq(pinned, []);
  eq(content.querySelectorAll(".dec").filter((d) => d.dataset.status !== "open").length, 0);
  eq(content.querySelector(".dec-sum-count").textContent, "0 of 7 answered");
});

test("a pick shows as sent while the page is busy, and Change my mind takes it back", () => {
  const { content, id } = mount([DEC("D1", "easy")]);
  press(content, "Go with Claude's suggestion");
  eq(content.querySelector(".dec").dataset.status, "picked");
  press(content, "Change my mind");
  eq(removed, [[id, "D1"]]);
  eq(content.querySelector(".dec").dataset.status, "open");
  press(content, "Go with Claude's suggestion");
  document.body.classList.add("is-busy");
  document.dispatchEvent(new ShimEvent("annotate:busy"));   // the page says it is busy
  eq(content.querySelector(".dec").dataset.status, "sent");
  eq(content.querySelector(".dec-state").textContent, "Sent, Claude is updating");
  eq(content.querySelectorAll(".dec-btn").length, 0, "a sent card has no buttons");
});

test("a plain comment on a decision leaves it open and says so", () => {
  const { content, id } = mount([DEC("D1", "easy")]);
  marks.set(id + "|D1", { kind: "comment", text: "Is this safe?" });
  press(content, "Write my own");
  eq(content.querySelector(".dec").dataset.status, "open");
  eq(content.querySelectorAll(".dec-next").map((x) => x.textContent)[0], "Your comment is in the round. This question is still open.");
});

test("an answered card says what was chosen and what changed, and Change my answer reopens it", () => {
  const { content } = mount([DEC("D1", "easy", { status: "answered", chosen: "b", outcome: "The plan now uses B." }),
                             DEC("D2", "easy", { status: "answered", answer: "Both, A first." })]);
  const [d1, d2] = content.querySelectorAll(".dec");
  eq([d1.dataset.status, d2.dataset.status], ["answered", "answered"]);
  eq(d1.querySelector(".dec-mine").textContent, "You chose: Label B D1");
  eq(d1.querySelector(".dec-outc").textContent, "Claude changed the plan: The plan now uses B.");
  eq(d2.querySelector(".dec-mine").textContent, "Your own words: Both, A first.");
  eq(content.querySelector(".dec-sum-count").textContent, "2 of 2 answered");
  eq(pinned, [], "nothing pinned by reopening");
  press(content, "Change my answer");
  eq(content.querySelectorAll(".dec")[0].dataset.status, "open");
  eq(pinned, []);
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

test("a facts strip is not a comment target, and spec words are text, never HTML", () => {
  const c = paint("facts", { facts: [{ value: "<b>x</b>", label: "<i>y</i>" }, { value: "2", label: "z" }] });
  eq(c.querySelectorAll(".fact").length, 2);
  eq(c.querySelectorAll("[data-annotate-id]").length, 0);
  eq(c.querySelectorAll("button").length, 0);
  eq(c.querySelectorAll("b").length, 0);
  eq(c.querySelector(".fact-value").textContent, "<b>x</b>");
});

process.stdout.write(`${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
