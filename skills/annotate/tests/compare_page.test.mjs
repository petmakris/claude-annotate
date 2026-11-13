#!/usr/bin/env node
/* Three bits of annotate page code that touch a compare part, run on the shared DOM shim:
 * a live edit of a compare part rebuilds its section (script-reconcile.js), a compare side with no
 * label is headed "Before" or "After" (script-blocks.js), and the maximized view of a diagram has
 * a Fit width button while a compare part has none (maximize.js). Nothing is laid out.
 * Run: node skills/annotate/tests/compare_page.test.mjs */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import { install, document } from "../../_shared/tests/dom_shim.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (f) => readFileSync(path.join(here, "..", "static", f), "utf8");
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
// The text of the file from one marker up to the next.
function slice(file, from, to) {
  const s = src(file), a = s.indexOf(from), b = s.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error("cannot find " + from + " in " + file);
  return s.slice(a, b);
}

// ---- script-reconcile.js: updateBlockContent --------------------------------------------------
Object.assign(globalThis, {
  blockMd: { render: (t) => "<p>" + t + "</p>" },
  sanitizeFreeHtml() {}, setBlockLabel() {}, renderCodeColumn: () => null,
  clearUpdatingOverlay() {}, untrackMockupFrames() {},
  paintVz() {}, paintFlowchart() {},
  createBlockSection(blk) {
    const s = document.createElement("section");
    s.className = "block"; s.dataset.kind = blk.kind; s.dataset.fresh = "yes";
    return s;
  },
});
vm.runInThisContext(slice("script-reconcile.js", "function focusWithin", "// ── Boot")
  + "\n;globalThis.__u = updateBlockContent;");
const updateBlockContent = globalThis.__u;
function sectionOf(kind) {
  const host = document.createElement("main");
  const s = document.createElement("section");
  s.className = "block"; s.dataset.kind = kind;
  const c = document.createElement("div"); c.className = "block-content";
  s.append(c); host.append(s);
  return { host, s };
}

test("a live edit of a compare part is rebuilt as a fresh section", () => {
  const { host, s } = sectionOf("compare");
  const out = updateBlockContent(s, { id: "section-1", kind: "compare", version: 2, spec: {} }, 2);
  eq(out === s, false, "same node");
  eq(out.dataset.fresh, "yes");
  eq(host.firstChild === out, true, "the fresh section took its place");
});

test("a markdown part is repainted in place, not rebuilt", () => {
  const { s } = sectionOf("markdown");
  const out = updateBlockContent(s, { id: "section-1", kind: "markdown", version: 3, markdown: "hi" }, 3);
  eq(out === s, true);
  eq(s.querySelector(".block-content").innerHTML, "<p>hi</p>");
});

// ---- script-blocks.js: comparePane -----------------------------------------------------------
vm.runInThisContext(slice("script-blocks.js", "function comparePane", "function renderCompare")
  + "\n;globalThis.__c = comparePane;");
const comparePane = globalThis.__c;
const labelOf = (which, side) => comparePane(which, side, []).querySelector(".cmp-label").textContent;

test("a compare side with no label is headed Before or After", () => {
  eq(labelOf("before", {}), "Before");
  eq(labelOf("after", {}), "After");
});

test("a compare side keeps the label it was given", () => {
  eq(labelOf("before", { label: "Today · master" }), "Today · master");
  eq(labelOf("after", { label: "Proposed" }), "Proposed");
});

// ---- maximize.js: the Fit width button ------------------------------------------------------
document.body.innerHTML = '<main class="prose"></main>';
const prose = document.querySelector("main.prose");
for (const kind of ["flowchart", "compare"]) {
  const s = document.createElement("section");
  s.className = "block"; s.dataset.kind = kind; s.dataset.blockId = kind;
  const h = document.createElement("div"); h.className = "block-frame-head";
  s.append(h); prose.append(s);
}
Object.assign(globalThis, { unfoldFor() {} });
vm.runInThisContext(src("maximize.js"));
const fit = () => [...document.querySelectorAll(".max-btn")].find((b) => b.textContent === "Fit width");
function openKind(kind) {
  window.AnnotateMaximize.open(document.querySelector(`section[data-block-id="${kind}"]`));
  return fit().hidden;
}

test("the maximized view of a diagram shows Fit width", () => {
  eq(openKind("flowchart"), false);
});

test("the maximized view of a compare part hides Fit width", () => {
  eq(openKind("compare"), true);
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
