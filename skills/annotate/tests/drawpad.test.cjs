#!/usr/bin/env node
/* The drawing pad's geometry. Run: node skills/annotate/tests/drawpad.test.cjs */
const path = require("path");
global.window = {};
require(path.join(__dirname, "..", "static", "drawpad.js"));
const { widthAt, bounds, hits, zoomAbout, fitView } = window.DrawPad._geometry;

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
const round = (o) => JSON.parse(JSON.stringify(o, (k, v) => typeof v === "number" ? Math.round(v * 1000) / 1000 : v));

test("a mouse or finger, with no pressure, draws at the chosen size times 0.85", () => {
  eq(widthAt(4, 0, "pen"), 3.4);
  eq(widthAt(4, 0.5, "pen"), 3.4);
});

test("a pen's pressure spans 0.35 to 1.35 times the size", () => {
  eq(round(widthAt(4, 0.01, "pen")), 1.44);
  eq(widthAt(4, 1, "pen"), 5.4);
});

test("the marker is three times the size whatever the pressure", () => {
  eq(widthAt(4, 0.1, "marker"), 12);
  eq(widthAt(4, 1, "marker"), 12);
});

test("an empty drawing has no bounds", () => {
  eq(bounds([]), null);
});

test("the bounds take in half the widest line on every side", () => {
  const s = { tool: "pen", size: 4, points: [[10, 20, 0.5], [110, 70, 0.5]] };
  eq(round(bounds([s])), { x: 7.3, y: 17.3, w: 105.4, h: 55.4 });
});

test("the eraser hits a line within its reach and misses one beyond it", () => {
  const s = { tool: "pen", size: 4, points: [[0, 0, 0.5], [100, 0, 0.5]] };
  eq(hits(s, 50, 12, 10), true, "12 from the line, reach 10 + 2.7");
  eq(hits(s, 50, 13, 10), false, "13 from the line");
  eq(hits(s, 112, 0, 10), true, "past the end, inside the round cap");
});

test("a dot is hit around its one point", () => {
  const s = { tool: "pen", size: 2, points: [[5, 5, 0.5]] };
  eq(hits(s, 5, 16, 10), true);
  eq(hits(s, 5, 17, 10), false);
});

test("zooming keeps the point under the fingers where it was", () => {
  const view = { scale: 1, x: 30, y: -40 };
  const out = zoomAbout(view, 200, 100, 2);
  eq(out, { scale: 2, x: -140, y: -180 });
  // The world point under (200, 100) before and after.
  eq([(200 - view.x) / view.scale, (100 - view.y) / view.scale], [(200 - out.x) / out.scale, (100 - out.y) / out.scale]);
});

test("zoom stops at 0.2 and 8", () => {
  eq(zoomAbout({ scale: 1, x: 0, y: 0 }, 0, 0, 100).scale, 8);
  eq(zoomAbout({ scale: 1, x: 0, y: 0 }, 0, 0, 0.001).scale, 0.2);
});

test("fit centres a small drawing at 1:1 and never zooms in", () => {
  eq(fitView({ x: 0, y: 0, w: 100, h: 50 }, 1000, 800, 32), { scale: 1, x: 450, y: 375 });
});

test("fit shrinks a large drawing to the screen less the margin", () => {
  eq(round(fitView({ x: 0, y: 0, w: 2000, h: 500 }, 1064, 800, 32)), { scale: 0.5, x: 32, y: 275 });
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
