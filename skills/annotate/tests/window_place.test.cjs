#!/usr/bin/env node
/* Where the comment window opens. Run: node skills/annotate/tests/window_place.test.cjs */
const path = require("path");
const { place, clamp, MIN } = require(path.join(__dirname, "..", "static", "window-place.js"));

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
const overlaps = (w, s) => w.left < s.right && s.left < w.left + w.width && w.top < s.bottom && s.top < w.top + w.height;

test("with room beside the text it opens there, level with the selection", () => {
  const out = place({ sel: { left: 100, top: 300, right: 500, bottom: 340 }, content: { left: 40, top: 0, right: 900, bottom: 3000 },
                      view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(out, { left: 916, top: 290, width: 420, height: 280 });
});

test("with no room beside the text it stays off the selected words", () => {
  const sel = { left: 60, top: 300, right: 700, bottom: 360 };
  const out = place({ sel, content: { left: 40, top: 0, right: 1460, bottom: 3000 }, view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(overlaps(out, sel), false, "covers the selection");
  eq(out.left + out.width <= 1500 - 16 && out.top >= 16 && out.top + out.height <= 1000 - 16, true, "off screen");
});

test("a selection across the full width puts the window below it", () => {
  const sel = { left: 40, top: 200, right: 1460, bottom: 260 };
  const out = place({ sel, content: { left: 40, top: 0, right: 1460, bottom: 3000 }, view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(out.top, 272);
  eq(overlaps(out, sel), false);
});

test("near the bottom it goes above the selection", () => {
  const sel = { left: 40, top: 800, right: 1460, bottom: 860 };
  const out = place({ sel, content: { left: 40, top: 0, right: 1460, bottom: 3000 }, view: { w: 1500, h: 1000 }, size: { w: 420, h: 280 } });
  eq(out.top, 800 - 12 - 280);
});

test("on a narrow screen it is full width less a 16px gutter", () => {
  const out = place({ sel: { left: 16, top: 100, right: 300, bottom: 140 }, content: { left: 16, top: 0, right: 374, bottom: 3000 },
                      view: { w: 390, h: 800 }, size: { w: 420, h: 280 } });
  eq([out.left, out.width], [16, 358]);
  eq(out.top, 152);
});

test("a remembered size below the minimum is raised to it", () => {
  const out = place({ sel: { left: 100, top: 300, right: 500, bottom: 340 }, content: { left: 40, top: 0, right: 900, bottom: 3000 },
                      view: { w: 1500, h: 1000 }, size: { w: 10, h: 10 } });
  eq([out.width, out.height], [MIN.w, MIN.h]);
});

test("a window left off screen by a smaller browser is pulled back", () => {
  eq(clamp({ left: 1300, top: 900, width: 420, height: 280 }, { w: 1000, h: 700 }), { left: 564, top: 404, width: 420, height: 280 });
  eq(clamp({ left: -50, top: -20, width: 2000, height: 900 }, { w: 1000, h: 700 }), { left: 16, top: 16, width: 968, height: 668 });
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
