#!/usr/bin/env node
/* The page width is a slider from 40% to 100% of the window, in steps of 5.
 * It is the reader's, one value for every annotate document. It runs the
 * real script-settings.js on the shared DOM shim, which lays nothing out, so
 * this checks what the page paints (data-width, --content-max, the slider
 * and its words), never a measured width.
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
const KEY = "annotate.view:pagewidth";
// Where a width was kept when it was one per document.
const OLD_KEY = "annotate.view:r1:pagewidth";

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

test("a stored share reads as itself, snapped to the step and clamped", () => {
  eq(widthFromStored("70%"), "70%");
  eq(widthFromStored("72%"), "70%");
  eq(widthFromStored("10%"), "40%");
  eq(widthFromStored("150%"), "100%");
});

test("a width kept as pixels reads as the share of the window it drew", () => {
  eq(widthFromStored("960", 1600), "60%");
  eq(widthFromStored("1280", 1440), "90%");
  eq(widthFromStored("full", 1440), "100%");
  eq(widthFromStored("wide", 1440), "100%");
  eq(widthFromStored("normal", 1520), "50%");
});

test("nothing stored, or something unknown, is 90%", () => {
  eq(widthFromStored(null), "90%");
  eq(widthFromStored("narrow"), "90%");
  eq(widthFromStored("12em"), "90%");
});

test("a page with no choice paints 90% and the slider says so", () => {
  wireViewControls();
  eq(painted(), ["90%", "max(90vw, 600px)"]);
  eq(slider().value, "90");
  eq([slider().min, slider().max, slider().step], ["40", "100", "5"]);
  eq(shown(), "90%");
});

test("dragging paints and stores each share as it goes", () => {
  drag(70);
  eq(painted(), ["70%", "max(70vw, 600px)"]);
  eq(shown(), "70%");
  eq(localStorage.getItem(KEY), "70%");
  drag(45);
  eq(painted(), ["45%", "max(45vw, 600px)"]);
  eq(localStorage.getItem(KEY), "45%");
});

test("100% is the whole window, with no cap", () => {
  drag(100);
  eq(painted(), ["100%", "none"]);
  eq(shown(), "100%");
  eq(localStorage.getItem(KEY), "100%");
});

test("a width chosen in one document opens every other one at that width", () => {
  drag(80);
  document.body.focus();
  document.body.dataset.responseId = "r2";
  applyViewControls();
  eq(painted(), ["80%", "max(80vw, 600px)"]);
  eq(slider().value, "80");
  document.body.dataset.responseId = "r1";
});

test("a width this document kept before is used until one is chosen for all", () => {
  document.body.focus();
  localStorage.removeItem(KEY);
  localStorage.setItem(OLD_KEY, "65%");
  applyViewControls();
  eq(painted(), ["65%", "max(65vw, 600px)"]);
  drag(60);
  eq(localStorage.getItem(KEY), "60%");
  document.body.focus();
  applyViewControls();
  eq(painted(), ["60%", "max(60vw, 600px)"]);
});

test("Reset puts the width back to 90%, the old per-document one too", () => {
  drag(90);
  localStorage.setItem(OLD_KEY, "65%");
  document.body.focus();
  vm.runInThisContext("resetSettings()");
  eq(localStorage.getItem(KEY), null);
  eq(localStorage.getItem(OLD_KEY), null);
  eq(painted(), ["90%", "max(90vw, 600px)"]);
  eq(shown(), "90%");
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
