#!/usr/bin/env node
/* The page width is a slider: 600px to 1600px, then Full. It runs the real
 * script-settings.js on the shared DOM shim, which lays nothing out, so this
 * checks what the page paints (data-width, --content-max, the slider and its
 * words), never a measured width.
 * Run: node skills/annotate/tests/page_width.test.mjs */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import { install, document, ShimEvent } from "../../_shared/tests/dom_shim.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
install();
document.body.dataset.responseId = "r1";
const groups = document.createElement("div");
groups.id = "settings-groups";
document.body.append(groups);
vm.runInThisContext(readFileSync(path.join(here, "..", "static", "script-settings.js"), "utf8")
  + "\n;globalThis.__w = { widthFromStored, wireViewControls, applyViewControls };");
const { widthFromStored, wireViewControls, applyViewControls } = globalThis.__w;
const KEY = "annotate.view:r1:pagewidth";

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
const slider = () => groups.querySelector('[data-setting="pagewidth"] input');
const shown = () => groups.querySelector('[data-setting="pagewidth"] .set-value').textContent;
const painted = () => [document.body.dataset.width, document.body.style.getPropertyValue("--content-max")];
function drag(to) {
  slider().focus();
  slider().value = String(to);
  slider().dispatchEvent(new ShimEvent("input", { bubbles: true }));
}

test("a stored width reads as itself, snapped to the step and clamped", () => {
  eq(widthFromStored("960"), "960");
  eq(widthFromStored("963"), "960");
  eq(widthFromStored("100"), "600");
  eq(widthFromStored("9000"), "1600");
  eq(widthFromStored("full"), "full");
});

test("the old stops read as the widths they drew", () => {
  eq(widthFromStored("normal"), "760");
  eq(widthFromStored("wide"), "full");
});

test("nothing stored, or something unknown, is 760px", () => {
  eq(widthFromStored(null), "760");
  eq(widthFromStored("narrow"), "760");
  eq(widthFromStored("12em"), "760");
});

test("a page with no choice paints 760px and the slider says so", () => {
  wireViewControls();
  eq(painted(), ["760", "760px"]);
  eq(slider().value, "760");
  eq([slider().min, slider().max, slider().step], ["600", "1620", "20"]);
  eq(shown(), "760 px");
});

test("dragging paints and stores each width as it goes", () => {
  drag(1000);
  eq(painted(), ["1000", "1000px"]);
  eq(shown(), "1000 px");
  eq(localStorage.getItem(KEY), "1000");
  drag(640);
  eq(painted(), ["640", "640px"]);
  eq(localStorage.getItem(KEY), "640");
});

test("the slider's last stop is Full, with no cap", () => {
  drag(1620);
  eq(painted(), ["full", "none"]);
  eq(shown(), "Full");
  eq(localStorage.getItem(KEY), "full");
});

test("a saved Wide opens at Full and a saved Normal at 760px", () => {
  document.body.focus();
  localStorage.setItem(KEY, "wide");
  applyViewControls();
  eq(painted(), ["full", "none"]);
  eq(slider().value, "1620");
  localStorage.setItem(KEY, "normal");
  applyViewControls();
  eq(painted(), ["760", "760px"]);
  eq(slider().value, "760");
});

test("Reset puts the width back to 760px", () => {
  drag(1200);
  document.body.focus();
  vm.runInThisContext("resetSettings()");
  eq(localStorage.getItem(KEY), null);
  eq(painted(), ["760", "760px"]);
  eq(shown(), "760 px");
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
