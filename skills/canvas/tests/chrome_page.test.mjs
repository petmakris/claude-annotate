#!/usr/bin/env node
/* The canvas page's chrome (canvas-chrome.js) on the shared DOM shim: the brief a canvas opens with,
 * the banner that takes its place, and the failure link. It checks what the page writes, never layout.
 * Run: node skills/canvas/tests/chrome_page.test.mjs */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import { install, document } from "../../_shared/tests/dom_shim.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const CHROME = readFileSync(path.join(here, "..", "static", "canvas-chrome.js"), "utf8");
install();

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

// Build the page's chrome from this data and hand back the banner.
function chrome(data) {
  const d = { title: "T", groups: [{ name: "G", boards: [{ status: "ok" }] }], ...data };
  document.body.innerHTML = '<header id="top"></header><div class="banner" id="banner" role="alert" hidden></div>'
    + '<div id="canvas"></div><script type="application/json" id="canvas-data">' + JSON.stringify(d) + "</script>";
  vm.runInThisContext(CHROME);
  return document.getElementById("banner");
}
const BRIEF = [{ heading: "Goal", text: "Show the screens" }, { heading: "Scope", text: "Desktop & phone" }];

test("a canvas with a brief and no banner opens with the brief", () => {
  const b = chrome({ brief: BRIEF });
  eq(b.hidden, false);
  eq(b.className, "banner brief");
  eq(b.innerHTML, "<section><h2>Goal</h2><p>Show the screens</p></section>"
    + "<section><h2>Scope</h2><p>Desktop &amp; phone</p></section>");
});

test("a banner takes the place of the brief", () => {
  const b = chrome({ brief: BRIEF, banner: "Stopped early" });
  eq(b.hidden, false);
  eq(b.className, "banner");
  eq(b.innerHTML, "Stopped early");
});

test("an empty brief and no banner leave the banner hidden", () => {
  eq(chrome({ brief: [] }).hidden, true);
  eq(chrome({}).hidden, true);
});

test("a banner with a failed board links to where it stopped", () => {
  const b = chrome({ banner: "Run stopped", groups: [{ name: "G", boards: [{ status: "ok" }, { status: "failure" }] }] });
  eq(b.innerHTML, 'Run stopped <a href="#failure">See where it stopped</a>.');
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
